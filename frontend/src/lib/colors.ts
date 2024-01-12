import { LifecycleToggle } from '~/types'

import { LemonTagType } from './lemon-ui/LemonTag'

/** --brand-blue in HSL for saturation mixing */
export const BRAND_BLUE_HSL: [number, number, number] = [228, 100, 56]

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
]

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
        throw new Error(`Couldn't find color variable --${variable}`)
    }
    return colorValue.trim()
}

/** Return a series color value. Hexadecimal format as Chart.js doesn't work with CSS vars.
 *
 * @param index The index of the series color.
 * @param numSeries Number of series in the insight being visualized.
 * @param comparePrevious If true, wrapped colors ()
 * @param asBackgroundHighlight If true, add opacity to color
 */
export function getSeriesColor(
    index: number | undefined = 0,
    comparePrevious: boolean | null = false,
    asBackgroundHighlight?: boolean
): string {
    const adjustedIndex = (comparePrevious ? Math.floor(index / 2) : index) % dataColorVars.length
    const isPreviousPeriodSeries = comparePrevious && index % 2 === 1
    const baseHex = getColorVar(`data-${dataColorVars[adjustedIndex]}`)
    return isPreviousPeriodSeries ? `${baseHex}80` : asBackgroundHighlight ? `${baseHex}30` : baseHex
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

/**
 * Gradate color saturation based on its intended strength.
 * This is for visualizations where a data point's color depends on its value.
 * @param hsl The HSL color to gradate.
 * @param strength The strength of the data point.
 * @param floor The minimum saturation. This preserves proportionality of strength, so doesn't just cut it off.
 */
export function gradateColor(
    hsl: [number, number, number],
    strength: number,
    floor: number = 0
): `hsla(${number}, ${number}%, ${number}%, ${string})` {
    const saturation = floor + (1 - floor) * strength
    return `hsla(${hsl[0]}, ${hsl[1]}%, ${hsl[2]}%, ${saturation.toPrecision(3)})`
}
