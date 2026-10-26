"""Write latin subsets of the RoundHog fonts from @posthog/brand into public/fonts/roundhog.

The full RoundHog files are about 120 KB each, and most of that is glyphs for scripts the app
rarely shows. fonts.scss loads these subsets for the latin range and keeps the full files for
all other characters, so a browser fetches a full file only when a page needs it.

Run this after a @posthog/brand upgrade changes the fonts, or after a change to the latin
unicode-range in fonts.scss:

    uv run --with 'fonttools[woff]==4.62.1' python frontend/bin/subset-roundhog-fonts.py
"""

import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FRONTEND = Path(__file__).resolve().parents[1]
SOURCE = FRONTEND / "node_modules" / "@posthog" / "brand" / "dist" / "fonts"
TARGET = FRONTEND / "public" / "fonts" / "roundhog"
FONTS_SCSS = FRONTEND / "src" / "styles" / "fonts.scss"

# The app turns on only the browser default features and tnum, pnum and case. Leaving out the
# stylistic sets and character variants keeps their alternate glyphs out of the subset.
LAYOUT_FEATURES = [*subset.Options().layout_features, "tnum", "pnum", "case"]


def latin_codepoints() -> list[int]:
    match = re.search(r"-latin\.woff2.*?unicode-range:([^;]+);", FONTS_SCSS.read_text(), re.DOTALL)
    if match is None:
        raise SystemExit(f"No latin unicode-range in {FONTS_SCSS}")
    return subset.parse_unicodes(match.group(1))


def subset_font(source: Path, codepoints: list[int]) -> None:
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = LAYOUT_FEATURES
    font = TTFont(source, recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)
    subset.save_font(font, TARGET / f"{source.stem}-latin.woff2", options)


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    codepoints = latin_codepoints()
    for source in SOURCE.glob("RoundHog*.woff2"):
        subset_font(source, codepoints)


if __name__ == "__main__":
    main()
