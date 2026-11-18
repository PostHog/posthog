import { createContext, useCallback, useContext, useSyncExternalStore } from 'react'

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

// Shares of the host's ink color. There is no token for these: the graph tokens carry no dash
// pattern, and `--color-graph-axis-line` is one value doing both the grid and the axis line.
const INK_SHARE = { grid: 6, axisLine: 35, crosshair: 22 } as const

const DASH_PATTERN: readonly number[] = [3, 3]

/** `color-mix` rather than a JS blend: the input is `oklch()`, which `d3.color` can't parse, and
 *  these values only reach `ctx.strokeStyle`, where the browser resolves them. */
function inkShare(foreground: string | undefined, percent: number): string | undefined {
    return foreground ? `color-mix(in oklab, ${foreground} ${percent}%, transparent)` : undefined
}

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
 * Grid, axis-line and crosshair styling as a partial theme. {@link themeFromCssVars} already
 * includes it — call this directly only when a host reads the palette through its own token reader
 * and wants the same styling on top.
 */
export function themeDefaultsFromCssVars(options: ThemeFromCssOptions = {}): Partial<ChartTheme> {
    const dashes = { gridDashPattern: [...DASH_PATTERN], crosshairDashPattern: [...DASH_PATTERN] }
    if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
        return dashes
    }
    const style = getComputedStyle(options.root ?? document.body)
    const foreground = readCssVar(style, '--foreground') ?? readCssVar(style, '--color-text-primary')
    return {
        ...dashes,
        // Graph tokens as the fallback, for a host that ships them without an ink color.
        gridColor: inkShare(foreground, INK_SHARE.grid) ?? readCssVar(style, '--color-graph-axis-line'),
        axisLineColor: inkShare(foreground, INK_SHARE.axisLine),
        crosshairColor: inkShare(foreground, INK_SHARE.crosshair) ?? readCssVar(style, '--color-graph-crosshair'),
    }
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
        ...themeDefaultsFromCssVars({ root }),
        colors,
        backgroundColor: readCssVar(style, '--background') ?? readCssVar(style, '--color-bg-surface-primary'),
        axisColor: readCssVar(style, '--color-graph-axis-label'),
        // Surface-styled like quill's popover, not its inverse hint tooltip — stays dark in dark mode.
        // Compat fallback matches the app's buildTheme() (--color-bg-surface-popover in lib/colors.ts).
        tooltipBackground: readCssVar(style, '--card') ?? readCssVar(style, '--color-bg-surface-popover'),
        tooltipColor: readCssVar(style, '--foreground') ?? readCssVar(style, '--color-text-primary'),
    }
}

interface ThemeStore {
    readonly options: ThemeFromCssOptions
    theme: ChartTheme
    /** Set while no observer runs, because a theme change in that time goes unseen. */
    needsRead: boolean
    readonly listeners: Set<() => void>
    observer: MutationObserver | null
}

const FALLBACK_THEME: ChartTheme = { colors: [...DEFAULT_CHART_COLORS] }

const WATCHED_ATTRIBUTES: MutationObserverInit = { attributes: true, attributeFilter: ['class', 'theme', 'data-theme'] }

// Store key for an omitted `root`. The read resolves `document.body` at call time, so the key can't be the element.
const DEFAULT_ROOT = {}
const stores = new WeakMap<object, Map<number, ThemeStore>>()

function getStore(root: HTMLElement | undefined, colorCount: number): ThemeStore {
    const key = root ?? DEFAULT_ROOT
    let byColorCount = stores.get(key)
    if (!byColorCount) {
        byColorCount = new Map()
        stores.set(key, byColorCount)
    }
    let store = byColorCount.get(colorCount)
    if (!store) {
        store = {
            options: { root, colorCount },
            theme: FALLBACK_THEME,
            needsRead: true,
            listeners: new Set(),
            observer: null,
        }
        byColorCount.set(colorCount, store)
    }
    return store
}

function sameValue(a: unknown, b: unknown): boolean {
    if (Array.isArray(a) && Array.isArray(b)) {
        return a.length === b.length && a.every((item, i) => item === b[i])
    }
    return a === b
}

function sameTheme(a: ChartTheme, b: ChartTheme): boolean {
    const keys = Object.keys(a) as (keyof ChartTheme)[]
    return keys.length === Object.keys(b).length && keys.every((key) => sameValue(a[key], b[key]))
}

function refresh(store: ThemeStore): boolean {
    store.needsRead = false
    const next = themeFromCssVars(store.options)
    if (sameTheme(store.theme, next)) {
        return false
    }
    store.theme = next
    return true
}

function readSnapshot(store: ThemeStore): ChartTheme {
    if (store.needsRead) {
        refresh(store)
    }
    return store.theme
}

function subscribe(store: ThemeStore, listener: () => void): () => void {
    store.listeners.add(listener)
    if (!store.observer && typeof MutationObserver === 'function') {
        const onMutation = (): void => {
            if (refresh(store)) {
                store.listeners.forEach((notify) => notify())
            }
        }
        store.observer = new MutationObserver(onMutation)
        store.observer.observe(document.documentElement, WATCHED_ATTRIBUTES)
        store.observer.observe(document.body, WATCHED_ATTRIBUTES)
        // The theme can change between the first render and this subscribe.
        onMutation()
    }
    return () => {
        store.listeners.delete(listener)
        if (store.listeners.size === 0) {
            store.observer?.disconnect()
            store.observer = null
            store.needsRead = true
        }
    }
}

const getServerSnapshot = (): ChartTheme => FALLBACK_THEME

/**
 * React hook returning a {@link ChartTheme} read from the quill data-viz CSS
 * vars, kept in sync as the active theme changes. Watches the `class` / `theme`
 * attributes on both `<html>` and `<body>` (different toggling conventions set
 * one or the other) and re-reads the vars whenever they flip.
 * Callers with the same options share one object, so treat it as read-only.
 */
export function useChartTheme(options: ThemeFromCssOptions = {}): ChartTheme {
    return useCssVarTheme(options, true)
}

const noopUnsubscribe = (): void => {}

function useCssVarTheme(options: ThemeFromCssOptions, enabled: boolean): ChartTheme {
    const store = getStore(options.root, options.colorCount ?? DEFAULT_CHART_COLORS.length)
    const subscribeToStore = useCallback(
        (listener: () => void) => (enabled ? subscribe(store, listener) : noopUnsubscribe),
        [store, enabled]
    )
    const getSnapshot = useCallback(() => (enabled ? readSnapshot(store) : FALLBACK_THEME), [store, enabled])
    return useSyncExternalStore(subscribeToStore, getSnapshot, getServerSnapshot)
}

const ChartThemeContext = createContext<ChartTheme | null>(null)

/** Gives every chart below it a theme, so a chart can omit its `theme` prop. Pass the result of
 *  {@link useChartTheme} (or the host's own theme hook) as `value`. A new `value` object repaints
 *  every chart below, so keep it stable. */
export const ChartThemeProvider = ChartThemeContext.Provider

/** The theme a chart draws with: its own `theme` prop, else the nearest {@link ChartThemeProvider},
 *  else the quill CSS vars. Only the last case reads and watches the CSS vars. */
export function useResolvedChartTheme(theme?: ChartTheme): ChartTheme {
    const provided = useContext(ChartThemeContext)
    const fallback = useCssVarTheme({}, !theme && !provided)
    return theme ?? provided ?? fallback
}
