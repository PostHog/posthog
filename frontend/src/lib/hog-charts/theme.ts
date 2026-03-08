import type { HogChartTheme } from './types'

export const hogColors = [
    '#1D4AFF', // blue
    '#CD0F74', // magenta
    '#43827E', // teal
    '#621DA6', // purple
    '#F04F58', // red
    '#147DF5', // sky
    '#E4A604', // amber
    '#1AA35C', // green
    '#7C440E', // brown
    '#C73AC8', // pink
    '#26C0C0', // cyan
    '#CF6C00', // orange
    '#568AF2', // periwinkle
    '#8F2DB8', // violet
    '#B64B02', // rust
] as const

export const lifecycleColors = {
    new: '#1AA35C',
    returning: '#1D4AFF',
    resurrecting: '#C73AC8',
    dormant: '#F04F58',
} as const

export const defaultTheme: HogChartTheme = {
    colors: [...hogColors],
    fontFamily:
        '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
    fontSize: 12,
    backgroundColor: 'transparent',
    axisColor: '#94949480',
    gridColor: '#94949420',
    goalLineColor: '#F04F58',
    tooltipBackground: '#1D1F27',
    tooltipColor: '#EEEEEE',
    tooltipBorderRadius: 8,
}

export function mergeTheme(overrides?: Partial<HogChartTheme>): HogChartTheme {
    if (!overrides) {
        return defaultTheme
    }
    return { ...defaultTheme, ...overrides }
}

export function seriesColor(theme: HogChartTheme, index: number): string {
    return theme.colors[index % theme.colors.length]
}
