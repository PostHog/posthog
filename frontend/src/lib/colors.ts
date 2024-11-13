import { captureException } from '@sentry/react'

import { LifecycleToggle } from '~/types'

import { LemonTagType } from './lemon-ui/LemonTag'


/* Insight series colors. */
const dataColorVars = [
    'color-1',
    'color-2',
    'color-3',
    'color-4',
    'color-5',
    'color-6',
    'color-7',
    'color-8',
    'color-9',
    'color-10',
    'color-11',
    'color-12',
    'color-13',
    'color-14',
    'color-15',
] as const

export type DataColorToken = `preset-{1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15}`

export type DataColorTheme = Record<DataColorToken, string>

export const tagColors: LemonTagType[] = [
    'primary',
    'highlight',
    'warning',
    'danger',
    'success',
    'completion',
    'caution',
    'option',
]

export function getColorVar(variable: string): string {
    const colorValue = getComputedStyle(document.body).getPropertyValue('--' + variable)
    if (!colorValue) {
        captureException(new Error(`Couldn't find color variable --${variable}`))
        // Fall back to black or white depending on the theme
        return document.body.getAttribute('theme') === 'light' ? '#000' : '#fff'
    }
    return colorValue.trim()
}

export function getDataThemeColor(theme: DataColorTheme, color: DataColorToken): string {
    return theme[color]
}

/** Returns the color for the given series index.
 *
 * The returned colors are in hex format for compatibility with Chart.js. They repeat
 * after all possible values have been exhausted.
 *
 * @param index The index of the series color.
 */
export function getSeriesColor(index: number = 0): string {
    const adjustedIndex = index % dataColorVars.length
    return getColorVar(`data-${dataColorVars[adjustedIndex]}`)
}

/** Returns all color options for series */
export function getSeriesColorPalette(): string[] {
    return dataColorVars.map((colorVar) => getColorVar(`data-${colorVar}`))
}

/** Return the background color for the given series index. */
export function getSeriesBackgroundColor(index: number): string {
    return `${getSeriesColor(index)}30`
}

/** Returns the color for the given series index. When comparing against previous ... */
export function getTrendLikeSeriesColor(index: number, isPrevious: boolean): string {
    const baseHex = getSeriesColor(index)
    return isPrevious ? `${baseHex}80` : baseHex
}

/** Return hexadecimal color value for lifecycle status.
 *
 * Hexadecimal is necessary as Chart.js doesn't work with CSS vars.
 */
export function getBarColorFromStatus(status: LifecycleToggle, hover?: boolean): string {
    switch (status) {
        case 'new':
        case 'returning':
        case 'resurrecting':
        case 'dormant':
            return getColorVar(`lifecycle-${status}${hover ? '-hover' : ''}`)
        default:
            throw new Error(`Unknown lifecycle status: ${status}`)
    }
}

export function getGraphColors(isDarkModeOn: boolean): Record<string, string | null> {
    return {
        axisLabel: isDarkModeOn ? '#fff' : '#2d2d2d', // --text-3000
        axisLine: isDarkModeOn ? '#4b4d58' : '#ddd', // --funnel-grid
        axis: isDarkModeOn ? '#4b4d58' : '#999',
        crosshair: isDarkModeOn ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
        tooltipBackground: '#1dc9b7',
        tooltipTitle: '#fff',
        tooltipBody: '#fff',
    }
}
