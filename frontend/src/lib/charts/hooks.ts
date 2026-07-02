import { useValues } from 'kea'
import { useMemo } from 'react'

import type { ChartTheme } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { buildTheme } from './utils/theme'

/** Rendering options the refreshed style turns on. Applied as config *defaults* — a chart's own
 *  config always wins. All four are stable quill-charts config keys, so removing the flag later
 *  means inlining these at the call sites (or flipping the library defaults), not deleting an API. */
const REFRESHED_CONFIG_DEFAULTS = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
} as const

function refreshedThemeOverrides(isDarkModeOn: boolean): Partial<ChartTheme> {
    return {
        gridColor: isDarkModeOn ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        gridDashPattern: [3, 3],
        axisLineColor: isDarkModeOn ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
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

/** Merges the refreshed rendering defaults (monotone curve, axis lines, tick marks, crosshair)
 *  under a chart's config when `QUILL_CHART_STYLE_REFRESH` is enabled. Keys the config sets
 *  explicitly (non-undefined) always win. Pass a stable (memoized) config object. */
export function useRefreshedChartConfig<T extends object>(config: T): T {
    const refreshEnabled = useChartStyleRefreshEnabled()
    return useMemo(() => {
        if (!refreshEnabled) {
            return config
        }
        const defined = Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined))
        return { ...REFRESHED_CONFIG_DEFAULTS, ...defined } as T
    }, [refreshEnabled, config])
}
