#!/usr/bin/env python3
"""Print --color-product-* variables that step a sidebar group through a gradient.

Usage:
    python3 sidebar_gradient.py GROUP name-one name-two ...

GROUP is one of the gradient groups below. Pass the color variable names in the order the
sidebar shows the entries, which is alphabetical by label within a category. Paste the output
over the matching lines in frontend/src/styles/base.scss.
"""

import sys
import colorsys

# (light start, light end, dark start, dark end) as RGB.
GROUPS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "ai-engineering": ((99, 102, 241), (196, 60, 218), (129, 140, 248), (232, 121, 249)),
    "cdp": ((234, 179, 8), (194, 65, 12), (253, 224, 71), (249, 115, 22)),
    "schema": ((20, 184, 166), (29, 78, 216), (94, 234, 212), (96, 165, 250)),
    "tools": ((239, 68, 68), (217, 40, 160), (252, 165, 165), (244, 114, 208)),
}


def gradient(start: tuple[int, int, int], end: tuple[int, int, int], steps: int) -> list[tuple[int, int, int]]:
    """Interpolate in HSL along the shorter way around the hue circle, so a warm range stays warm."""
    h1, l1, s1 = colorsys.rgb_to_hls(*(c / 255 for c in start))
    h2, l2, s2 = colorsys.rgb_to_hls(*(c / 255 for c in end))
    dh = h2 - h1
    if dh > 0.5:
        dh -= 1
    elif dh < -0.5:
        dh += 1
    colors: list[tuple[int, int, int]] = []
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 0
        r, g, b = colorsys.hls_to_rgb((h1 + dh * t) % 1, l1 + (l2 - l1) * t, s1 + (s2 - s1) * t)
        colors.append((round(r * 255), round(g * 255), round(b * 255)))
    return colors


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in GROUPS:
        sys.exit(f"usage: {sys.argv[0]} {{{','.join(GROUPS)}}} name [name ...]")
    light_start, light_end, dark_start, dark_end = GROUPS[sys.argv[1]]
    names = sys.argv[2:]
    for name, light, dark in zip(
        names, gradient(light_start, light_end, len(names)), gradient(dark_start, dark_end, len(names))
    ):
        sys.stdout.write(f"    --color-product-{name}-light: rgb({light[0]} {light[1]} {light[2]});\n")
        sys.stdout.write(f"    --color-product-{name}-dark: rgb({dark[0]} {dark[1]} {dark[2]});\n")


if __name__ == "__main__":
    main()
