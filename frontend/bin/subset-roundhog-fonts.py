"""Write latin subsets of the RoundHog fonts from @posthog/brand into public/fonts/roundhog.

The full RoundHog files are about 120 KB each, and most of that is glyphs for scripts the app
rarely shows. fonts.scss loads these subsets for the latin range and keeps the full files for
all other characters, so a browser fetches a full file only when a page needs it.

Run this after a @posthog/brand upgrade changes the fonts:

    uv run --with 'fonttools[woff]==4.62.1' python frontend/bin/subset-roundhog-fonts.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FRONTEND = Path(__file__).resolve().parents[1]
SOURCE = FRONTEND / "node_modules" / "@posthog" / "brand" / "dist" / "fonts"
TARGET = FRONTEND / "public" / "fonts" / "roundhog"

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


@dataclass(frozen=True, slots=True)
class CodepointRange:
    first: int
    last: int

    def css(self) -> str:
        return f"U+{self.first:04X}" if self.first == self.last else f"U+{self.first:04X}-{self.last:04X}"


# Both faces carry the combining marks. A browser draws a letter and its marks with one face,
# so a mark missing from the letter's face sends the whole cluster to a fallback font.
COMBINING_MARKS = CodepointRange(0x0300, 0x036F)

# The app turns on only the browser default features and the numeric ones. Leaving out the
# stylistic sets and character variants keeps their alternate glyphs out of the subset.
LAYOUT_FEATURES = [*subset.Options().layout_features, "tnum", "pnum", "case"]

# Keep in sync with the latin unicode-range in src/styles/fonts.scss.
# The Google Fonts latin range, plus the arrows, math, keyboard, box drawing and dingbat blocks that the UI uses.
LATIN_RANGES = [
    CodepointRange(0x0000, 0x00FF),
    CodepointRange(0x0131, 0x0131),
    CodepointRange(0x0152, 0x0153),
    CodepointRange(0x02BB, 0x02BC),
    CodepointRange(0x02C6, 0x02C6),
    CodepointRange(0x02DA, 0x02DA),
    CodepointRange(0x02DC, 0x02DC),
    COMBINING_MARKS,
    CodepointRange(0x2000, 0x206F),
    CodepointRange(0x20AC, 0x20AC),
    CodepointRange(0x2122, 0x2122),
    CodepointRange(0x2190, 0x23FF),
    CodepointRange(0x2500, 0x27BF),
    CodepointRange(0xFEFF, 0xFEFF),
    CodepointRange(0xFFFD, 0xFFFD),
]


def css_range(ranges: list[CodepointRange]) -> str:
    return ", ".join(r.css() for r in ranges)


def complement(ranges: list[CodepointRange]) -> list[CodepointRange]:
    result = []
    start = 0
    for r in sorted(ranges, key=lambda r: r.first):
        if r.first > start:
            result.append(CodepointRange(start, r.first - 1))
        start = r.last + 1
    if start <= 0x10FFFF:
        result.append(CodepointRange(start, 0x10FFFF))
    return result


def subset_font(name: str) -> None:
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = LAYOUT_FEATURES
    font = TTFont(SOURCE / f"{name}.woff2", recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[cp for r in LATIN_RANGES for cp in range(r.first, r.last + 1)])
    subsetter.subset(font)
    subset.save_font(font, TARGET / f"{name}-latin.woff2", options)


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in FONTS:
        subset_font(name)
    sys.stdout.write(f"latin range: {css_range(LATIN_RANGES)}\n")
    other = sorted([*complement(LATIN_RANGES), COMBINING_MARKS], key=lambda r: r.first)
    sys.stdout.write(f"other range: {css_range(other)}\n")


if __name__ == "__main__":
    main()
