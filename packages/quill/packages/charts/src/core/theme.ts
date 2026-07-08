import { useEffect, useState } from 'react'

import type { ChartTheme } from './types'

/**
 * Fallback categorical palette, used only when the `--data-color-*` CSS vars
 * aren't loaded (no `@posthog/quill-tokens` stylesheet, or SSR with no DOM).
 *
 * Charts are headless — colors normally come from the host's design tokens via
 * {@link themeFromCssVars}. `@posthog/quill-tokens` is the source of truth for
 * these values (`dataColorPalette`); this literal copy keeps the package's
 * runtime dependency-free so a missing stylesheet degrades to a visible palette
 * instead of black. `theme.test.ts` asserts it stays equal to the token palette,
 * so the duplication can't silently drift — update both together.
 */
export const DEFAULT_CHART_COLORS: readonly string[] = [
    '#1d4aff',
    '#621da6',
    '#42827e',
    '#ce0e74',
    '#f14f58',
    '#7c440e',
    '#529a0a',
    '#0476fb',
    '#fe729e',
    '#35416b',
    '#41cbc4',
    '#b64b02',
    '#e4a604',
    '#a56eff',
    '#30d5c8',
]

export interface ThemeFromCssOptions {
    /**
     * Element whose computed styles are read. Token vars defined on `:root`
     * inherit down to any element, and dark-mode overrides applied to `<body>`
     * (the visual test-runner flips `body[theme="dark"]`) are only visible at
     * or below `<body>` — so the default is `document.body`, not `<html>`.
     */
    root?: HTMLElement
    /** How many `--data-color-N` vars to read (default 15, the token count). */
    colorCount?: number
}

function readCssVar(style: CSSStyleDeclaration, name: string): string | undefined {
    return style.getPropertyValue(name).trim() || undefined
}

/**
 * Build a {@link ChartTheme} from the quill data-viz CSS vars
 * (`--data-color-*`, `--color-graph-*`, surface/text tokens). Reads computed
 * styles once; pair with {@link useChartTheme} to re-read on theme changes.
 *
 * Safe on the server / before mount: returns the fallback palette when there's
 * no DOM.
 */
export function themeFromCssVars(options: ThemeFromCssOptions = {}): ChartTheme {
    const { colorCount = DEFAULT_CHART_COLORS.length } = options

    if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
        return { colors: [...DEFAULT_CHART_COLORS] }
    }

    const root = options.root ?? document.body
    const style = getComputedStyle(root)

    const colors = Array.from(
        { length: colorCount },
        (_, i) => readCssVar(style, `--data-color-${i + 1}`) ?? DEFAULT_CHART_COLORS[i % DEFAULT_CHART_COLORS.length]
    )

    // Prefer quill's own tokens; the app's `--color-*` names are a compat
    // fallback only, so the design-system package never depends on app naming.
    return {
        colors,
        backgroundColor: readCssVar(style, '--background') ?? readCssVar(style, '--color-bg-surface-primary'),
        axisColor: readCssVar(style, '--color-graph-axis-label'),
        gridColor: readCssVar(style, '--color-graph-axis-line'),
        crosshairColor: readCssVar(style, '--color-graph-crosshair'),
        // Surface-styled like quill's popover, not its inverse hint tooltip — stays dark in dark mode.
        // Compat fallback matches the app's buildTheme() (--color-bg-surface-popover in lib/colors.ts).
        tooltipBackground: readCssVar(style, '--card') ?? readCssVar(style, '--color-bg-surface-popover'),
        tooltipColor: readCssVar(style, '--foreground') ?? readCssVar(style, '--color-text-primary'),
    }
}

/**
 * React hook returning a {@link ChartTheme} read from the quill data-viz CSS
 * vars, kept in sync as the active theme changes. Watches the `class` / `theme`
 * attributes on both `<html>` and `<body>` (different toggling conventions set
 * one or the other) and re-reads the vars whenever they flip.
 */
export function useChartTheme(options: ThemeFromCssOptions = {}): ChartTheme {
    const { root, colorCount } = options
    const [theme, setTheme] = useState<ChartTheme>(() => themeFromCssVars(options))

    useEffect(() => {
        if (typeof document === 'undefined' || typeof MutationObserver !== 'function') {
            return
        }
        const reread = (): void => setTheme(themeFromCssVars({ root, colorCount }))
        reread()
        const observer = new MutationObserver(reread)
        const opts: MutationObserverInit = { attributes: true, attributeFilter: ['class', 'theme', 'data-theme'] }
        observer.observe(document.documentElement, opts)
        observer.observe(document.body, opts)
        return () => observer.disconnect()
        // root/colorCount are the only inputs; options identity is intentionally ignored.
    }, [root, colorCount])

    return theme
}
