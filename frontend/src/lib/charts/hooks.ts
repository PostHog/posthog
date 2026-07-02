import { useValues } from 'kea'
import { type DependencyList, useMemo } from 'react'

import type { ChartTheme } from '@posthog/quill-charts'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { buildTheme } from './utils/theme'

/** Theme for app quill charts. `buildTheme()` reads CSS variables from the DOM, so the memo keys on
 *  `isDarkModeOn` to re-read them when the app theme flips. Pass a stable (memoized or module-level)
 *  `overrides` object — a fresh object every render defeats the memo. */
export function useChartTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const { isDarkModeOn } = useValues(themeLogic)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return useMemo(() => buildTheme(overrides), [isDarkModeOn, overrides])
}

/** Drop-in replacement for the `useMemo` that builds a chart's config object. This is the central
 *  seam for applying app-level rendering defaults to every quill chart config — currently a plain
 *  memo; config defaults (with the chart's own keys winning) hook in here. */
export function useChartConfig<T extends object>(factory: () => T, deps: DependencyList): T
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined
export function useChartConfig<T extends object>(factory: () => T | undefined, deps: DependencyList): T | undefined {
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return useMemo(factory, deps)
}
