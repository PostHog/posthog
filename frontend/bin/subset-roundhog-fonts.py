"""Write latin subsets of the RoundHog fonts from @posthog/brand into public/fonts/roundhog.

The full RoundHog files are about 120 KB each, and most of that is glyphs for scripts the app
rarely shows. fonts.scss loads these subsets for the latin range and keeps the full files for
all other characters, so a browser fetches a full file only when a page needs it.

Run this after a @posthog/brand upgrade changes the fonts:

    uv run --with fonttools python frontend/bin/subset-roundhog-fonts.py
"""

import sys
import json
import hashlib
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FRONTEND = Path(__file__).resolve().parents[1]
SOURCE = FRONTEND / "node_modules" / "@posthog" / "brand" / "dist" / "fonts"
TARGET = FRONTEND / "public" / "fonts" / "roundhog"
MANIFEST = TARGET / "manifest.json"

FONTS = [
    "RoundHog",
    "RoundHog-Italic",
    "RoundHog-Medium",
    "RoundHog-Medium-Italic",
    "RoundHog-SemiBold",
    "RoundHog-SemiBold-Italic",
    "RoundHog-Bold",
    "RoundHog-Bold-Italic",
]

# Keep in sync with the latin unicode-range in src/styles/fonts.scss.
# The Google Fonts latin range, plus the arrows, math, keyboard, box drawing and dingbat blocks that the UI uses.
LATIN_RANGES = [
    (0x0000, 0x00FF),
    (0x0131, 0x0131),
    (0x0152, 0x0153),
    (0x02BB, 0x02BC),
    (0x02C6, 0x02C6),
    (0x02DA, 0x02DA),
    (0x02DC, 0x02DC),
    (0x0304, 0x0304),
    (0x0308, 0x0308),
    (0x0329, 0x0329),
    (0x2000, 0x206F),
    (0x20AC, 0x20AC),
    (0x2122, 0x2122),
    (0x2190, 0x23FF),
    (0x2500, 0x27BF),
    (0xFEFF, 0xFEFF),
    (0xFFFD, 0xFFFD),
]


def css_range(ranges: list[tuple[int, int]]) -> str:
    return ", ".join(f"U+{lo:04X}" if lo == hi else f"U+{lo:04X}-{hi:04X}" for lo, hi in ranges)


def complement(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    start = 0
    for lo, hi in sorted(ranges):
        if lo > start:
            result.append((start, lo - 1))
        start = hi + 1
    if start <= 0x10FFFF:
        result.append((start, 0x10FFFF))
    return result


def subset_font(name: str) -> str:
    source = SOURCE / f"{name}.woff2"
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    font = TTFont(source, recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[cp for lo, hi in LATIN_RANGES for cp in range(lo, hi + 1)])
    subsetter.subset(font)
    subset.save_font(font, TARGET / f"{name}-latin.woff2", options)
    return hashlib.sha256(source.read_bytes()).hexdigest()


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": {f"{name}.woff2": subset_font(name) for name in FONTS}}
    MANIFEST.write_text(json.dumps(manifest, indent=4) + "\n")
    sys.stdout.write(f"latin range: {css_range(LATIN_RANGES)}\n")
    sys.stdout.write(f"other range: {css_range(complement(LATIN_RANGES))}\n")


if __name__ == "__main__":
    main()
