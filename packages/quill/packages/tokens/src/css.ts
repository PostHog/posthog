/**
 * Shared CSS generation helpers for token files.
 */

/** Generate CSS custom property lines from a flat key-value map */
export function cssVars(tokens: Record<string, string>, prefix: string, indent = '  '): string {
    return Object.entries(tokens)
        .map(([k, v]) => `${indent}--${prefix}-${k}: ${v};`)
        .join('\n')
}

/** Generate CSS custom property lines without a prefix */
export function cssVarsFlat(tokens: Record<string, string>, indent = '  '): string {
    return Object.entries(tokens)
        .map(([k, v]) => `${indent}--${k}: ${v};`)
        .join('\n')
}

/** Quote a font name if it contains spaces, otherwise return as-is */
export function quoteFontName(name: string): string {
    return /\s/.test(name) ? `"${name}"` : name
}

/** Format a font family array as a CSS value */
export function fontFamilyValue(fonts: readonly string[]): string {
    return fonts.map(quoteFontName).join(', ')
}
