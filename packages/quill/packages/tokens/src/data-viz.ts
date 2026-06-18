/**
 * PostHog Design System — Data-visualization tokens
 *
 * Two kinds of token live here, both consumed by `@posthog/quill-charts`
 * (charts ship no CSS — they read these vars into a `ChartTheme` at runtime):
 *
 *  1. A **categorical palette** (`--data-color-1..N`) — an ordered, qualitative
 *     scale charts index into for series colors. Distinct from the semantic
 *     color map in `colors.ts`: order is meaningful, hues must stay mutually
 *     distinguishable, and the values are static brand hexes (NOT derived from
 *     `--theme-hue`). Only the shades that need extra contrast carry a dark
 *     override; the rest reuse the light value.
 *
 *  2. **Graph chrome** vars (axis labels, grid lines, crosshair) — aliased onto
 *     existing semantic tokens so they flip with light/dark automatically and
 *     need no separate dark block.
 *
 * Var names match the PostHog app's historical `--data-color-*` /
 * `--color-graph-*` so the app can drop its local definitions and inherit
 * these instead.
 */

/** `[light, dark?]` — omit `dark` to reuse the light value in both modes. */
export type DataColorTuple = readonly [light: string, dark?: string]

/** Ordered categorical series palette. Index 0 → `--data-color-1`. */
export const dataColors: readonly DataColorTuple[] = [
    ['#1d4aff'],
    ['#621da6', '#7f26d9'],
    ['#42827e', '#3e7a76'],
    ['#ce0e74', '#bf0d6c'],
    ['#f14f58', '#f0474f'],
    ['#7c440e', '#b36114'],
    ['#529a0a'],
    ['#0476fb'],
    ['#fe729e'],
    ['#35416b', '#6576b3'],
    ['#41cbc4'],
    ['#b64b02'],
    ['#e4a604'],
    ['#a56eff'],
    ['#30d5c8'],
] as const

/** Light-mode palette as a plain array — for JS consumers and as a sensible
 *  fallback when the CSS vars aren't loaded (see quill-charts `DEFAULT_CHART_COLORS`). */
export const dataColorPalette: readonly string[] = dataColors.map(([light]) => light)

/** CSS custom property name for the categorical color at `index` (0-based). */
export function dataColorVarName(index: number): string {
    return `--data-color-${index + 1}`
}

/** Graph chrome tokens, aliased onto semantic vars so they track theme mode. */
const graphChrome: Record<string, string> = {
    '--color-graph-axis-label': 'var(--muted-foreground)',
    '--color-graph-axis-line': 'var(--border)',
    '--color-graph-crosshair': 'var(--muted-foreground)',
}

/**
 * CSS var lines for the data-viz tokens, split by mode. Injected into
 * `color-system.css` alongside the static semantic colors (these are not
 * theme-hue-derived, so `:root` / the scope selector is the right home).
 *
 * - `light`: full palette + graph chrome.
 * - `dark`: only the palette entries that define an override.
 */
export function generateDataVizVars(indent = '  '): { light: string; dark: string } {
    const lightLines = [
        ...dataColors.map(([light], i) => `${indent}${dataColorVarName(i)}: ${light};`),
        ...Object.entries(graphChrome).map(([name, value]) => `${indent}${name}: ${value};`),
    ]
    const darkLines = dataColors
        .map(([, dark], i) => (dark ? `${indent}${dataColorVarName(i)}: ${dark};` : null))
        .filter((line): line is string => line !== null)

    return { light: lightLines.join('\n'), dark: darkLines.join('\n') }
}
