import { captureException } from '@sentry/react'

import { LifecycleToggle } from '~/types'

import { LemonTagType } from './lemon-ui/LemonTag'

/*
 * Data colors.
 */

/** CSS variable names for the default posthog theme data colors. */
const dataColorVars = [
    'data-color-1',
    'data-color-2',
    'data-color-3',
    'data-color-4',
    'data-color-5',
    'data-color-6',
    'data-color-7',
    'data-color-8',
    'data-color-9',
    'data-color-10',
    'data-color-11',
    'data-color-12',
    'data-color-13',
    'data-color-14',
    'data-color-15',
] as const

export type DataColorToken =
    | 'preset-1'
    | 'preset-2'
    | 'preset-3'
    | 'preset-4'
    | 'preset-5'
    | 'preset-6'
    | 'preset-7'
    | 'preset-8'
    | 'preset-9'
    | 'preset-10'
    | 'preset-11'
    | 'preset-12'
    | 'preset-13'
    | 'preset-14'
    | 'preset-15'

export type DataColorTheme = Partial<Record<DataColorToken, string>> & {
    [key: `preset-${number}`]: string
}

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
    return theme[color] as string
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
    return getColorVar(dataColorVars[adjustedIndex])
}

/** Returns all color options for series */
export function getSeriesColorPalette(): string[] {
    return dataColorVars.map((colorVar) => getColorVar(colorVar))
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

/*
 * Tag colors.
 */

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
