import { useValues } from 'kea'
import { type DependencyList, useCallback, useMemo, useSyncExternalStore } from 'react'

import type { ChartTheme, DateRangeZoomData } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { themeLogic } from 'lib/logic/themeLogic'

import { buildTheme } from './utils/theme'

const REFRESHED_CONFIG_DEFAULTS = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    showGrid: true,
    barCornerRadius: 4,
} as const

function refreshedThemeOverrides(isDarkModeOn: boolean): Partial<ChartTheme> {
    return {
        gridColor: isDarkModeOn ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        gridDashPattern: [3, 3],
        axisLineColor: isDarkModeOn ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
        crosshairColor: isDarkModeOn ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.2)',
        crosshairDashPattern: [3, 3],
    }
}

export function useChartStyleRefreshEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return !!featureFlags[FEATURE_FLAGS.QUILL_CHART_STYLE_REFRESH]
}

function subscribeToBodyTheme(callback: () => void): () => void {
    if (typeof MutationObserver !== 'function') {
        return () => {}
    }
    const observer = new MutationObserver(callback)
    observer.observe(document.body, { attributes: true, attributeFilter: ['theme'] })
    return () => observer.disconnect()
}

function getBodyTheme(): string | null {
    return document.body.getAttribute('theme')
}

/** Theme for app quill charts. `buildTheme()` reads CSS variables from the DOM, so the memo re-reads
 *  them when the theme flips. Darkness is tracked via the `<body theme>` attribute rather than
 *  themeLogic alone: storybook snapshots flip that attribute directly on a mounted page without
 *  going through themeLogic, and canvas colors would otherwise stay stale (the app sets the same
 *  attribute via useThemedHtml, so both paths are covered). Behind `QUILL_CHART_STYLE_REFRESH` it
 *  also applies the refreshed chart colors (faint dashed grid, muted axis lines); caller `overrides`
 *  win over both. Pass a stable (memoized or module-level) `overrides` object — a fresh object every
 *  render defeats the memo. */
export function useChartTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const { isDarkModeOn } = useValues(themeLogic)
    const bodyTheme = useSyncExternalStore(subscribeToBodyTheme, getBodyTheme)
    const refreshEnabled = useChartStyleRefreshEnabled()
    const isDark = bodyTheme != null ? bodyTheme === 'dark' : isDarkModeOn
    return useMemo(
        () => buildTheme({ ...(refreshEnabled ? refreshedThemeOverrides(isDark) : {}), ...overrides }),
        [isDark, refreshEnabled, overrides]
    )
}

/** The single rollout gate for chart drag-to-zoom, applied inside `useDateRangeZoom` so every
 *  surface is enabled (and testable) through one check rather than per-host flag reads. */
export function useDragToZoomEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return !!featureFlags[FEATURE_FLAGS.INSIGHT_DRAG_TO_ZOOM]
}

/** Adapts a quill chart's drag-to-zoom callback to the host's `onZoom(dateFrom, dateTo)` by mapping
 *  the dragged label indices into `dates` — the date value for each x position (trends result days,
 *  a SQL date column's values). Both emitted dates are bucket *starts*; widening the end to the
 *  last bucket's end is the host's job (insights do it in `zoomDateRange`, which knows the query's
 *  interval). Returns undefined when zooming is unavailable — drag-to-zoom is opt-in: it only
 *  surfaces behind the rollout flag, where the host passes a handler, and when the x positions map
 *  to dates. */
export function useDateRangeZoom(
    dates: string[] | undefined,
    onZoom: ((dateFrom: string, dateTo: string) => void) | undefined
): ((data: DateRangeZoomData) => void) | undefined {
    const enabled = useDragToZoomEnabled()
    const handler = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData) => {
            const start = dates?.[startIndex]
            const end = dates?.[endIndex]
            if (!start || !end) {
                return
            }
            // Screen order isn't guaranteed chronological (e.g. unsorted SQL results).
            const [dateFrom, dateTo] = start <= end ? [start, end] : [end, start]
            onZoom?.(dateFrom, dateTo)
        },
        [dates, onZoom]
    )
    return enabled && dates?.length && onZoom ? handler : undefined
}

/** Drop-in replacement for the `useMemo` that builds a chart's config object. On top of memoizing,
 *  it applies app-level rendering defaults — currently the refreshed style (monotone curve, axis
 *  lines, tick marks, crosshair, grid) behind `QUILL_CHART_STYLE_REFRESH`. Keys the config sets
 *  explicitly (non-undefined) always win over the defaults. */
export function useChartConfig<T extends object>(factory: () => T, deps: DependencyList): T
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined {
    const refreshEnabled = useChartStyleRefreshEnabled()
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const config = useMemo(factory, deps)
    return useMemo(() => {
        if (!refreshEnabled || !config) {
            return config
        }
        const defined = Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined))
        return { ...REFRESHED_CONFIG_DEFAULTS, ...defined } as T
    }, [refreshEnabled, config])
}
