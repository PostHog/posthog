import { buildTheme, seriesColor } from 'lib/charts/utils/theme'

import type { HogChartTheme } from '../types'

export { seriesColor }

const hogChartDefaults: Partial<HogChartTheme> = {
    fontFamily:
        '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
    fontSize: 12,
    backgroundColor: 'transparent',
    goalLineColor: '#F04F58',
    tooltipBorderRadius: 8,
}

export function mergeTheme(overrides?: Partial<HogChartTheme>): HogChartTheme {
    const base = buildTheme()
    return { ...base, ...hogChartDefaults, ...overrides }
}
