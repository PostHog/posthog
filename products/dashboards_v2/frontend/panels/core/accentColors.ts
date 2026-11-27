/** The named colors a person can pick for a tile background or a tab. Plain data, so a saved document can be checked without React. */
export const ACCENT_COLOR_KEYS = ['blue', 'green', 'yellow', 'red', 'purple'] as const

export type AccentColor = (typeof ACCENT_COLOR_KEYS)[number]

/** Each is a theme color, so it follows light and dark mode. */
export const ACCENT_COLORS: Record<AccentColor, { label: string; css: string }> = {
    blue: { label: 'Blue', css: 'var(--color-blue-500)' },
    green: { label: 'Green', css: 'var(--color-green-500)' },
    yellow: { label: 'Yellow', css: 'var(--color-yellow-500)' },
    red: { label: 'Red', css: 'var(--color-red-500)' },
    purple: { label: 'Purple', css: 'var(--color-purple-500)' },
}

/** A custom color is saved as a hex code, so it can be checked as plain data. */
export const HEX_COLOR = /^#[0-9a-f]{6}$/i

/** A named color's CSS, or a custom hex color as it is. */
export function colorCss(color: string): string {
    return color in ACCENT_COLORS ? ACCENT_COLORS[color as AccentColor].css : color
}
