const RESOLVED_COLOR_MAP = new Map<string, string>()

/** Resolve CSS custom property values (e.g. `var(--my-color)`) to their computed hex/rgb string. Plain colors pass through unchanged. Results are cached. */
export function resolveVariableColor(color: string | undefined): string | undefined {
    if (!color) {
        return color
    }

    if (RESOLVED_COLOR_MAP.has(color)) {
        return RESOLVED_COLOR_MAP.get(color)
    }

    if (color.startsWith('var(--')) {
        const replaced = color.replace('var(', '').replace(')', '')
        const computedColor = getComputedStyle(document.documentElement).getPropertyValue(replaced)
        RESOLVED_COLOR_MAP.set(color, computedColor)
        return computedColor
    }

    RESOLVED_COLOR_MAP.set(color, color)

    return color
}
