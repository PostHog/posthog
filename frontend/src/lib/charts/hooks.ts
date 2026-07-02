import { useValues } from 'kea'
import { useMemo } from 'react'

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
