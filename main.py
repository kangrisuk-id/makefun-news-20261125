#!/usr/bin/env python3
"""THE WORLD TODAY - Wednesday 25 November 2026 in one image.

A pure-Python-stdlib newspaper front page. Draws a 1024x1024 PNG with its
own RGB framebuffer, its own PNG encoder (zlib + struct) and a glyph atlas
(glyphs.bin, rasterized at build time from DejaVu) that it blits at run
time. No third-party imports, no network, deterministic output.
"""
import os
import struct
import sys
import zlib

W = 1024
H = 1024

PAPER = (247, 242, 231)
CARD = (255, 253, 246)
INK = (26, 26, 24)
GREY = (96, 94, 88)
FAINT = (196, 188, 168)
RED = (176, 30, 36)
NAVY = (23, 54, 93)
TEAL = (14, 106, 102)
GOLD = (176, 132, 26)
GREEN = (22, 118, 52)
WHITE = (255, 255, 255)
DARK = (24, 26, 34)
SKY = (196, 216, 232)
SMOKE = (120, 118, 112)

# ---------------------------------------------------------------- atlas ----
def load_atlas(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    assert blob[:4] == b"GLY1"
    raw = zlib.decompress(blob[8:])
    pos = 0
    (nsets,) = struct.unpack_from("<H", raw, pos)
    pos += 2
    sets = {}
    for _ in range(nsets):
        size, bold, ascent, descent, count = struct.unpack_from(
            "<BBhhH", raw, pos)
        pos += 8
        glyphs = {}
        for _ in range(count):
            cp, adv, rawlen, gw, gh, ox, oy = struct.unpack_from(
                "<HhhBBbb", raw, pos)
            pos += 10
            glyphs[cp] = (adv, gw, gh, ox, oy, raw[pos:pos + rawlen])
            pos += rawlen
        sets[(size, bold)] = (ascent, descent, glyphs)
    return sets


ATLAS = None
SIZES = [9, 10, 11, 12, 13, 15, 17, 20, 26, 34, 46]


def pick_size(size):
    return min(SIZES, key=lambda s: abs(s - size))


# ------------------------------------------------------------ framebuffer --
class Canvas:
    def __init__(self, w, h, color):
        self.w = w
        self.h = h
        self.px = bytearray(bytes(color) * (w * h))

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(color)

    def blend(self, x, y, color, alpha):
        if alpha <= 0:
            return
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            if alpha >= 255:
                self.px[i:i + 3] = bytes(color)
            else:
                inv = 255 - alpha
                self.px[i] = (color[0] * alpha + self.px[i] * inv) // 255
                self.px[i + 1] = (color[1] * alpha + self.px[i + 1] * inv) // 255
                self.px[i + 2] = (color[2] * alpha + self.px[i + 2] * inv) // 255

    def rect(self, x, y, w, h, color):
        x0, x1 = max(0, x), min(self.w, x + w)
        y0, y1 = max(0, y), min(self.h, y + h)
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x, y, w, h, color, t=1):
        self.rect(x, y, w, t, color)
        self.rect(x, y + h - t, w, t, color)
        self.rect(x, y, t, h, color)
        self.rect(x + w - t, y, t, h, color)

    def line(self, x0, y0, x1, y1, color, t=1):
        dx, dy = x1 - x0, y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        for s in range(steps + 1):
            x = x0 + dx * s // steps
            y = y0 + dy * s // steps
            self.rect(x - t // 2, y - t // 2, t, t, color)

    def disc(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                    self.set(xx, yy, color)

    def poly(self, pts, color):
        ys = [p[1] for p in pts]
        for yy in range(min(ys), max(ys) + 1):
            nodes = []
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    nodes.append(x0 + (yy - y0) * (x1 - x0) // (y1 - y0))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                self.rect(nodes[i], yy, nodes[i + 1] - nodes[i], 1, color)

    # ------------------------------------------------------------- text --
    def measure(self, s, size, bold):
        size = pick_size(size)
        _, _, glyphs = ATLAS[(size, 1 if bold else 0)]
        total = 0
        for ch in s:
            g = glyphs.get(ord(ch)) or glyphs.get(63)
            if g:
                total += g[0]
        return total

    def text(self, x, y, s, size, bold, color, align="l"):
        size = pick_size(size)
        ascent, _, glyphs = ATLAS[(size, 1 if bold else 0)]
        if align == "c":
            x -= self.measure(s, size, bold) // 2
        elif align == "r":
            x -= self.measure(s, size, bold)
        cx = x
        for ch in s:
            g = glyphs.get(ord(ch)) or glyphs.get(63)
            if g is None:
                continue
            adv, gw, gh, ox, oy, raw = g
            for row in range(gh):
                base = row * gw
                for col in range(gw):
                    a = raw[base + col]
                    if a:
                        self.blend(cx + ox + col, y + oy + row, color, a)
            cx += adv
        return cx - x

    def line_h(self, size):
        size = pick_size(size)
        ascent, descent, _ = ATLAS[(size, 0)]
        return ascent + descent

    def wrap(self, s, size, bold, maxw):
        words = s.split()
        lines, cur = [], ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if self.measure(trial, size, bold) <= maxw or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def para(self, x, y, s, size, bold, color, maxw, leading=None,
             align="l"):
        leading = leading or (self.line_h(size) + 2)
        for ln in self.wrap(s, size, bold, maxw):
            tx = x
            if align == "c":
                tx = x + (maxw - self.measure(ln, size, bold)) // 2
            self.text(tx, y, ln, size, bold, color)
            y += leading
        return y

    def rich(self, x, y, head, body, size, maxw, leading=None):
        """Bold head followed by regular body, flowed as one paragraph."""
        leading = leading or (self.line_h(size) + 2)
        tokens = [(w, True) for w in head.split()]
        tokens += [(w, False) for w in body.split()]
        lines, cur, curw = [], [], 0
        space = self.measure(" ", size, False)
        for word, is_b in tokens:
            ww = self.measure(word, size, is_b)
            add = ww if not cur else ww + space
            if cur and curw + add > maxw:
                lines.append(cur)
                cur, curw = [(word, is_b)], ww
            else:
                cur.append((word, is_b))
                curw += add
        if cur:
            lines.append(cur)
        for line in lines:
            cx = x
            for word, is_b in line:
                self.text(cx, y, word, size, is_b, INK)
                cx += self.measure(word, size, is_b) + space
            y += leading
        return y


# ------------------------------------------------------------ png write ----
def png_bytes(cv):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    raw = bytearray()
    stride = cv.w * 3
    for yy in range(cv.h):
        raw.append(0)
        raw += cv.px[yy * stride:(yy + 1) * stride]
    idat = zlib.compress(bytes(raw), 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- scenes ---
def scene_ukraine(cv, x, y, w, h):
    cv.rect(x, y, w, h, SKY)
    cv.rect(x, y + h - 26, w, 26, (88, 84, 78))          # ground
    for i, bw in enumerate((34, 26, 44, 30, 38)):        # apartment blocks
        bx = x + 8 + i * (w // 5)
        bh = 34 + (i * 13) % 26
        cv.rect(bx, y + h - 26 - bh, bw - 6, bh, (70, 72, 80))
        for wy in range(y + h - 26 - bh + 5, y + h - 32, 9):
            for wx in range(bx + 4, bx + bw - 12, 9):
                cv.rect(wx, wy, 5, 5, (250, 214, 120))
    # fire + smoke on the middle block: small puffs drifting up-right
    bx = x + 8 + 2 * (w // 5)
    cv.poly([(bx + 8, y + 34), (bx + 20, y + 12), (bx + 30, y + 34)],
            (232, 110, 30))
    cv.poly([(bx + 13, y + 34), (bx + 20, y + 22), (bx + 26, y + 34)],
            (246, 178, 44))
    for dx, dy, r in ((30, 18, 6), (42, 12, 9), (56, 7, 12)):
        cv.disc(bx + dx, y + dy, r, (168, 166, 158))
    # drone silhouette
    dx, dy = x + w - 62, y + 14
    cv.rect(dx, dy, 26, 5, INK)
    cv.line(dx - 8, dy - 5, dx + 4, dy + 2, INK, 2)
    cv.line(dx + 22, dy + 2, dx + 34, dy - 5, INK, 2)
    cv.disc(dx + 13, dy + 8, 4, RED)


def scene_mine(cv, x, y, w, h):
    cv.rect(x, y, w, h, (214, 226, 208))
    cv.poly([(x, y + h), (x + w // 3, y + 8), (x + w * 2 // 3, y + h)],
            (104, 122, 84))                              # green slopes
    cv.poly([(x + w // 3, y + h), (x + w * 2 // 3, y + 10),
             (x + w, y + h)], (84, 102, 66))
    cv.rect(x + w // 3, y + h - 44, w // 3, 44, (52, 96, 140))  # flood water
    for i in range(4):
        cv.line(x + w // 3 + 6 + i * 8, y + h - 34 + (i % 2) * 8,
                x + w // 3 + 16 + i * 8, y + h - 34 + (i % 2) * 8,
                WHITE, 2)
    cv.rect(x + w // 2 - 16, y + 16, 6, h - 58, INK)     # shaft marker
    cv.rect(x + w // 2 - 4, y + 10, 62, 34, (247, 242, 231))
    cv.text(x + w // 2 + 2, y + 14, "100 m", 13, True, RED)
    cv.text(x + w // 2 + 2, y + 30, "deep", 11, False, INK)
    for i in range(3):                                   # rescue lamps
        cv.disc(x + 26 + i * 30, y + h - 52, 5, (250, 200, 60))
        cv.line(x + 26 + i * 30, y + h - 47, x + 26 + i * 30,
                y + h - 30, INK, 2)


def scene_markets(cv, x, y, w, h):
    cv.rect(x, y, w, h, (252, 244, 238))
    vals = [86, 78, 84, 70, 74, 60, 66, 46]
    bw = w // (len(vals) + 1)
    for i, v in enumerate(vals):
        bh = v * (h - 48) // 100
        cv.rect(x + 10 + i * bw, y + h - 18 - bh, bw - 8, bh,
                RED if i > 3 else GREEN)
    cv.line(x + 138, y + 12, x + w - 40, y + h - 34, RED, 3)  # plunge arrow
    cv.poly([(x + w - 40, y + h - 34), (x + w - 58, y + h - 36),
             (x + w - 44, y + h - 52)], RED)
    cv.rect(x + 6, y + 4, 132, 20, (252, 244, 238))
    cv.text(x + 10, y + 6, "NVIDIA -5.9%", 15, True, RED)
    cv.text(x + w - 96, y + h - 16, "CHIPS -7.9%", 11, True, INK)


# ------------------------------------------------------------------- map ---
# Land as (row, first column, length) dot segments on a 76 x 18 grid,
# designed for this page: the Americas left, Europe/Africa centre,
# Asia right, Indonesia and Australia lower right.
MAP_SEGMENTS = [
    # North America
    (1, 4, 15), (2, 3, 19), (3, 3, 20), (4, 4, 18), (5, 5, 15),
    (6, 6, 13), (7, 8, 9), (8, 10, 6),
    # South America
    (9, 17, 6), (10, 16, 8), (11, 16, 9), (12, 17, 8), (13, 17, 7),
    (14, 18, 5), (15, 18, 4), (16, 19, 2),
    # Europe
    (2, 35, 2), (2, 37, 8), (3, 36, 9), (4, 36, 8), (5, 37, 7),
    # Asia
    (1, 45, 27), (2, 45, 28), (3, 45, 29), (4, 44, 29), (5, 44, 25),
    (6, 44, 23), (7, 47, 18), (8, 50, 11), (8, 57, 4), (9, 58, 3),
    # Africa
    (7, 37, 10), (8, 37, 11), (9, 38, 10), (10, 38, 9), (11, 39, 7),
    (12, 40, 5), (13, 40, 4), (14, 41, 3),
    # Indonesia
    (10, 57, 3), (10, 61, 3), (11, 59, 4),
    # Australia
    (12, 63, 8), (13, 62, 10), (14, 64, 6),
]
MAP_COLS = 76
MAP_ROWS_N = 18

MARKERS = [
    ("1", 46, 4, "Odesa"), ("2", 44, 3, "Kyiv"), ("3", 37, 4, "Paris"),
    ("4", 60, 11, "Pongkor"), ("5", 55, 6, "Kathmandu"),
    ("6", 43, 5, "Antalya"), ("7", 47, 9, "Aden"), ("8", 45, 7, "Gaza"),
    ("9", 43, 11, "Ituri"), ("10", 20, 4, "New York"),
    ("11", 18, 6, "Washington"), ("12", 49, 8, "Doha"),
]


def draw_map(cv, x, y, w, h):
    pitch_x = w // MAP_COLS
    pitch_y = (h - 30) // MAP_ROWS_N
    for ri, c0, ln in MAP_SEGMENTS:
        for ci in range(c0, c0 + ln):
            cv.disc(x + ci * pitch_x + pitch_x // 2,
                    y + ri * pitch_y + pitch_y // 2, 2, NAVY)
    for num, gx, gy, _name in MARKERS:
        mx = x + gx * pitch_x + pitch_x // 2
        my = y + gy * pitch_y + pitch_y // 2
        cv.disc(mx, my, 6, RED)
        cv.text(mx, my - 5, num, 9, True, WHITE, align="c")
    legend = ("1 Odesa  2 Kyiv  3 Paris  4 Pongkor  5 Kathmandu  6 Antalya  "
              "7 Aden  8 Gaza  9 Ituri (DRC)  10 New York  11 Washington  "
              "12 Doha")
    cv.para(x + 2, y + h - 28, legend, 9, False, GREY, w - 4, leading=12)


# ----------------------------------------------------------------- page ----
def panel(cv, x, y, w, h, title, color):
    cv.rect(x, y, w, h, CARD)
    cv.frame(x, y, w, h, FAINT, 1)
    cv.rect(x, y, w, 17, color)
    cv.text(x + 6, y + 2, title, 12, True, WHITE)
    return y + 22


def build():
    cv = Canvas(W, H, PAPER)
    M = 16
    FW = W - 2 * M

    # masthead
    cv.rect(M, 10, FW, 4, INK)
    cv.text(W // 2, 18, "THE WORLD TODAY", 46, True, INK, align="c")
    cv.rect(M, 68, FW, 2, RED)
    cv.text(W // 2, 74,
            "Wednesday 25 November 2026  -  30 stories  -  7 regions  -  "
            "one page", 15, True, NAVY, align="c")
    cv.rect(M, 94, FW, 1, INK)

    # ---- leads ------------------------------------------------------------
    ly, lh = 100, 196
    lw = (FW - 16) // 3
    leads = [
        ("UKRAINE WAR", RED, scene_ukraine,
         "Russian strike kills 2 in Odesa; drones hit Kyiv",
         "A Russian strike on the Odesa region killed two people and hit "
         "cars and buildings. Drones attacked Kyiv, setting fire to an "
         "apartment block and injuring two. (Reuters)"),
        ("INDONESIA", TEAL, scene_mine,
         "Dozens trapped 100 m down in flooded gold mine",
         "Rescuers at Pongkor, West Java, searched for dozens of workers "
         "trapped about 100 m underground at a flooded unauthorised gold "
         "mine; some 30 have been trapped since Monday's rains. (Reuters)"),
        ("MARKETS REVERSE", GOLD, scene_markets,
         "Nvidia dives 5.9% as the chip rally unwinds",
         "Nvidia fell 5.9%, erasing Monday's rally on Jensen Huang's "
         "return. The Nasdaq lost 1.48% and the chip index 7.9%, while "
         "gold tested $3,550 an ounce. (Reuters / WSJ)"),
    ]
    for i, (tag, color, scene, head, body) in enumerate(leads):
        x = M + i * (lw + 8)
        cv.rect(x, ly, lw, 16, color)
        cv.text(x + 6, ly + 2, tag, 11, True, WHITE)
        scene(cv, x, ly + 20, lw, 76)
        yy = cv.para(x + 2, ly + 102, head, 15, True, INK, lw - 4,
                     leading=18)
        cv.para(x + 2, yy + 1, body, 11, False, INK, lw - 4, leading=14)
    cv.line(M, ly + lh, M + FW, ly + lh, INK, 1)

    # ---- stat strip -------------------------------------------------------
    sy = ly + lh + 6
    stats = [
        ("$125bn", "Ukraine's external support need for 2027 (Zelenskiy)"),
        ("74,746", "Gaza death toll, WAFA reports"),
        ("266M", "people facing acute food insecurity (WFP)"),
        ("15,164", "Indonesians in overseas scam cases this year"),
        ("204 off 53", "Sooryavanshi's record innings, 28 sixes"),
        ("-3.49%", "Bitcoin falls to $59,282"),
    ]
    sw = (FW - 5 * 6) // 6
    for i, (big, label) in enumerate(stats):
        x = M + i * (sw + 6)
        cv.rect(x, sy, sw, 52, CARD)
        cv.frame(x, sy, sw, 52, FAINT, 1)
        cv.text(x + sw // 2, sy + 4, big, 20, True, RED, align="c")
        cv.para(x + 4, sy + 28, label, 9, False, GREY, sw - 8, leading=11,
                align="c")

    # ---- map + markets ----------------------------------------------------
    my = sy + 60
    mh = 178
    mapw = 636
    cv.rect(M, my, mapw, mh, CARD)
    cv.frame(M, my, mapw, mh, FAINT, 1)
    cv.rect(M, my, mapw, 17, NAVY)
    cv.text(M + 6, my + 2, "THE DAY ON THE MAP - 12 PLACES IN THE NEWS",
            12, True, WHITE)
    draw_map(cv, M + 10, my + 24, mapw - 20, mh - 28)

    kx = M + mapw + 8
    kw = FW - mapw - 8
    yy = panel(cv, kx, my, kw, mh, "MARKETS - WEDNESDAY CLOSE", NAVY)
    markets = [
        ("Gold spot", "$3,544.54", "-0.3%", RED),
        ("Silver", "$40.79", "", INK),
        ("Bitcoin", "$59,282", "-3.49%", RED),
        ("Sensex", "83,846.74", "+1.71%", GREEN),
        ("Nifty", "25,735.60", "+1.52%", GREEN),
        ("Dow", "50,018.70", "+0.85%", GREEN),
        ("S&P 500", "7,201.09", "-0.50%", RED),
        ("Nasdaq", "23,733.54", "-1.48%", RED),
        ("Brent / WTI", "below $91 / $80.73", "", INK),
    ]
    for name, val, chg, cc in markets:
        cv.text(kx + 8, yy, name, 11, True, INK)
        cv.text(kx + kw - 8, yy, val + ("  " + chg if chg else ""), 11,
                False, cc, align="r")
        yy += 14
    cv.para(kx + 8, yy + 2,
            "Gold tested $3,550 after Tuesday's -2.2%. India rebounded "
            "while US tech fell.", 9, False, GREY, kw - 16, leading=11)

    # ---- region panels ----------------------------------------------------
    py = my + mh + 8
    ph = 122
    pw = (FW - 16) // 3
    regions = [
        ("EUROPE", NAVY, [
            ("Sarkozy to trial.",
             "France orders ex-President Sarkozy and Carla Bruni's "
             "corruption case to trial; pre-trial hearing 1 Apr 2027."),
            ("Sweden votes.",
             "Parliament to vote on whether PM Kristersson stays."),
            ("Berlin's budget bid.",
             "Germany seeks a rebate in the next EU budget and wants "
             "Ukraine aid anchored in it."),
        ]),
        ("ASIA-PACIFIC", TEAL, [
            ("India aids Nepal.",
             "New Delhi announces Rs 15,000 crore of development "
             "assistance for Nepal."),
            ("Nepal quake.",
             "Magnitude 5.3 quake sends tremors across Sikkim and "
             "North Bengal."),
            ("Shenzhou-24 crew.",
             "China selects a Pakistani astronaut as payload specialist "
             "for the mission."),
        ]),
        ("AMERICAS", RED, [
            ("Turkeys pardoned.",
             "Trump pardons Thanksgiving turkeys Freedom and Feathers; "
             "holiday staples cost 6% more, turkey 10%."),
            ("Medal for Giuliani.",
             "Trump awards Rudy Giuliani the Medal of Freedom."),
            ("Intelligence hack.",
             "CIA and ODNI hit by a cyberattack affecting classified "
             "information, CNN reports."),
        ]),
        ("MIDDLE EAST", GOLD, [
            ("Houthis near Aden.",
             "Rebels push to within 60 km of Aden; government forces say "
             "the city will not fall."),
            ("Gaza toll rises.",
             "Death toll reaches 74,746 amid Israeli attacks, WAFA says."),
            ("Pollution warning.",
             "Oxfam identifies pollution risks across more than 99% of "
             "Gaza."),
        ]),
        ("AFRICA", GREEN, [
            ("WHO evacuates.",
             "Staff leave a hospital in Akwe, Ituri, DRC, after three "
             "days sheltering from fighting."),
            ("Ebola record.",
             "DRC outbreak is the country's worst: 11,762 cases, 5,775 "
             "deaths; 53 tons of aid delivered."),
            ("RSF defection.",
             "An RSF commander defects and joins the Sudanese army with "
             "his troops."),
        ]),
        ("CLIMATE & WORLD", NAVY, [
            ("COP31 fails.",
             "Antalya summit ends without agreement - first failed COP "
             "since Copenhagen 2009; focus shifts to COP32 in Addis Ababa."),
            ("266M hungry.",
             "WFP counts 266 million people facing acute food "
             "insecurity worldwide."),
            ("Five women an hour.",
             "UN data: five women are killed every hour by partners or "
             "family members."),
        ]),
    ]
    for i, (title, color, stories) in enumerate(regions):
        x = M + (i % 3) * (pw + 8)
        y = py + (i // 3) * (ph + 6)
        yy = panel(cv, x, y, pw, ph, title, color)
        for head, body in stories:
            yy = cv.rich(x + 6, yy, head, body, 10, pw - 12, leading=12)
            yy += 2

    # ---- sport ------------------------------------------------------------
    yy0 = py + 2 * ph + 18
    yy = panel(cv, M, yy0, FW, 62, "SPORT", RED)
    sport = [
        ("204 off 53 balls.",
         "Vaibhav Sooryavanshi, 15, blasts 28 sixes as India A beat UAE "
         "by 7 wickets in Doha."),
        ("Arya's 181 off 68.",
         "Priyansh Arya hits the highest Syed Mushtaq Ali Trophy score "
         "as Delhi beat Tamil Nadu."),
        ("England level it.",
         "England beat Australia by 8 wickets chasing 185 to level the "
         "T20I series 1-1. Gukesh draws Game 1 of his title defence."),
    ]
    for i, (head, body) in enumerate(sport):
        x = M + i * (pw + 8)
        cv.rich(x + 6, yy, head, body, 10, pw - 12, leading=12)

    # ---- also today ticker --------------------------------------------------
    ty = yy0 + 68
    cv.rect(M, ty, FW, 74, DARK)
    cv.text(M + 8, ty + 4, "ALSO TODAY", 12, True, (250, 200, 60))
    ticker = ("Huawei convicted in New York on 10 of 12 counts incl. bank "
              "fraud and trade-secret theft  -  Fort Hood shooter Hasan "
              "seeks a stay of his execution set for next week  -  Radar "
              "outage delays flights at Chicago O'Hare, FAA says  -  "
              "Australia apologises to LGBTQ veterans for past military "
              "injustices  -  Indonesia foils recruitment of 21 citizens "
              "as mercenaries for Russia  -  India women beat China 6-2 in "
              "the Asian Champions Trophy hockey, Deepika hat-trick")
    cv.para(M + 8, ty + 22, ticker, 10, False, WHITE, FW - 16, leading=13)

    # ---- footer / date check ------------------------------------------------
    fy = ty + 80
    cv.rect(M, fy, FW, 2, RED)
    cv.para(M, fy + 6,
            "DATE CHECK: every story on this page was reported on "
            "Wednesday 25 November 2026, in at least one time zone - "
            "30 stories from 12 sources (Reuters, WAFA, WFP, WHO, CNN, "
            "WSJ and others). Full source list: NEWS_SOURCES.md.",
            10, True, NAVY, FW, leading=13, align="c")
    return png_bytes(cv)


def main():
    global ATLAS
    here = os.path.dirname(os.path.abspath(__file__))
    ATLAS = load_atlas(os.path.join(here, "glyphs.bin"))
    data = build()
    candidates = []
    env = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if env:
        candidates.append(env)
    candidates.append("/output")
    candidates.append(here)
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "entry.png")
            with open(path, "wb") as fh:
                fh.write(data)
            return 0
        except OSError:
            continue
    return 1


if __name__ == "__main__":
    sys.exit(main())
