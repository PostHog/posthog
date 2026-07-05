import { useValues } from 'kea'
import { type DependencyList, useMemo } from 'react'

import type { ChartTheme } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { buildTheme } from './utils/theme'

/** Rendering options the refreshed style turns on. Applied as config *defaults* — a chart's own
 *  config always wins. All five are stable quill-charts config keys, so removing the flag later
 *  means inlining these at the call sites (or flipping the library defaults), not deleting an API. */
const REFRESHED_CONFIG_DEFAULTS = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    // Stacked bars round only the outermost segment, so this reads as "curved bar tops".
    barCornerRadius: 4,
} as const

function refreshedThemeOverrides(isDarkModeOn: boolean): Partial<ChartTheme> {
    return {
        gridColor: isDarkModeOn ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        gridDashPattern: [3, 3],
        axisLineColor: isDarkModeOn ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
        // Dashed like the grid so the hover guide reads as a temporary sibling of the grid
        // lines, slightly stronger than them so it stays findable.
        crosshairColor: isDarkModeOn ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.2)',
        crosshairDashPattern: [3, 3],
    }
}

export function useChartStyleRefreshEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return !!featureFlags[FEATURE_FLAGS.QUILL_CHART_STYLE_REFRESH]
}

/** Theme for app quill charts. `buildTheme()` reads CSS variables from the DOM, so the memo keys on
 *  `isDarkModeOn` to re-read them when the app theme flips. Behind `QUILL_CHART_STYLE_REFRESH` it
 *  also applies the refreshed chart colors (faint dashed grid, muted axis lines); caller `overrides`
 *  win over both. Pass a stable (memoized or module-level) `overrides` object — a fresh object every
 *  render defeats the memo. */
export function useChartTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const { isDarkModeOn } = useValues(themeLogic)
    const refreshEnabled = useChartStyleRefreshEnabled()
    return useMemo(
        () => buildTheme({ ...(refreshEnabled ? refreshedThemeOverrides(isDarkModeOn) : {}), ...overrides }),
        [isDarkModeOn, refreshEnabled, overrides]
    )
}

/** Drop-in replacement for the `useMemo` that builds a chart's config object. On top of memoizing,
 *  it applies app-level rendering defaults — currently the refreshed style (monotone curve, axis
 *  lines, tick marks, crosshair) behind `QUILL_CHART_STYLE_REFRESH`. Keys the config sets
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
