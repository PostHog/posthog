import posthog from 'posthog-js'

import { RevenueAnalyticsMRRQueryResultItem } from '~/queries/schema/schema-general'
import { LifecycleToggle } from '~/types'

import { LemonTagType } from './lemon-ui/LemonTag'

/*
 * Data colors.
 */

/** CSS variable names for the default posthog theme data colors. */
export const dataColorVars = [
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
        posthog.captureException(new Error(`Couldn't find color variable --${variable}`))
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
export function getBarColorFromStatus(
    status: LifecycleToggle | `revenue-analytics-${keyof RevenueAnalyticsMRRQueryResultItem}`,
    hover?: boolean
): string {
    switch (status) {
        case 'new':
        case 'returning':
        case 'resurrecting':
        case 'dormant':
            return getColorVar(`color-lifecycle-${status}${hover ? '-hover' : ''}`)
        case 'revenue-analytics-new':
        case 'revenue-analytics-expansion':
        case 'revenue-analytics-contraction':
        case 'revenue-analytics-churn':
            return getColorVar(`color-${status}${hover ? '-hover' : ''}`)
        default:
            throw new Error(`Unknown lifecycle status: ${status}`)
    }
}

export function getGraphColors(): Record<string, string | null> {
    return {
        axisLabel: getColorVar('color-graph-axis-label'),
        axisLine: getColorVar('color-graph-axis-line'),
        axis: getColorVar('color-graph-axis'),
        crosshair: getColorVar('color-graph-crosshair'),

        // TODO: these are not used anywhere, but setting them to the correct values
        tooltipBackground: getColorVar('color-bg-surface-tooltip'),
        tooltipTitle: getColorVar('color-text-primary'),
        tooltipBody: getColorVar('color-bg-surface-tooltip'),
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
