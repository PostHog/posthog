import { useValues } from 'kea'
import { type DependencyList, useCallback, useEffect, useMemo, useState } from 'react'

import { DEFAULT_CHART_CONFIG } from '@posthog/quill-charts'
import type { ChartTheme, DateRangeZoomData } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { buildTheme } from './utils/theme'

/** `buildTheme()` reads CSS variables, so it can't be keyed on `isDarkModeOn`: `useThemedHtml` applies
 *  the theme by writing `document.body[theme]` from an effect, which runs after the render that
 *  flipped the value. Reading at render time therefore returns the outgoing theme's variables, and
 *  nothing recomputes them until the next reload — leaving axis labels in the previous mode's text
 *  color. Watching the attribute is independent of that ordering. */
function useCssVarTheme(): ChartTheme {
    const [theme, setTheme] = useState<ChartTheme>(buildTheme)

    useEffect(() => {
        let applied = document.body.getAttribute('theme')
        const reread = (): void => {
            const next = document.body.getAttribute('theme')
            if (next !== applied) {
                applied = next
                setTheme(buildTheme())
            }
        }
        // The attribute may already have been written between the first render and here.
        reread()

        const observer = new MutationObserver(reread)
        observer.observe(document.body, { attributeFilter: ['theme'] })
        return () => observer.disconnect()
    }, [])

    return theme
}

/** Theme for app quill charts. Pass a stable (memoized or module-level) `overrides` object — a fresh
 *  object every render defeats the memo. */
export function useChartTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const cssVarTheme = useCssVarTheme()
    return useMemo(() => ({ ...cssVarTheme, ...overrides }), [cssVarTheme, overrides])
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

/** Builds a chart's config object, memoized on `deps`, applying `DEFAULT_CHART_CONFIG` for any
 *  key the factory leaves undefined. Keys the factory sets explicitly always win over the defaults.
 *  `tooltip` merges key by key instead of being replaced wholesale. */
export function useChartConfig<T extends object>(factory: () => T, deps: DependencyList): T
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined {
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return useMemo(() => {
        const config = factory()
        if (!config) {
            return config
        }
        const defined = Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined))
        // Nested, so a chart that sets any tooltip field would otherwise replace the whole default.
        const tooltip = { ...DEFAULT_CHART_CONFIG.tooltip, ...defined.tooltip }
        return { ...DEFAULT_CHART_CONFIG, ...defined, tooltip } as T
    }, deps)
}
