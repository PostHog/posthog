/* Insight series colors. */
const dataColorVars = [
    'ultramarine',
    'purple',
    'viridian',
    'magenta',
    'vermilion',
    'brown',
    'green',
    'blue',
    'pink',
    'navy',
    'turquoise',
    'brick',
    'yellow',
    'lilac',
]

export const tagColors = [
    'blue',
    'cyan',
    'orange',
    'gold',
    'green',
    'lime',
    'volcano',
    'magenta',
    'purple',
    'red',
    'geekblue',
]

function getColorVar(variable: string): string {
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
 */
export function getSeriesColor(index: number | undefined = 0, comparePrevious: boolean = false): string {
    const adjustedIndex = (comparePrevious ? Math.floor(index / 2) : index) % dataColorVars.length
    const isPreviousPeriodSeries = comparePrevious && index % 2 === 1
    const baseHex = getColorVar(`data-${dataColorVars[adjustedIndex]}`)
    return isPreviousPeriodSeries ? `${baseHex}80` : baseHex
}

/** Return hexadecimal color value for lifecycle status.
 *
 * Hexadecimal is necessary as Chart.js doesn't work with CSS vars.
 */
export function getBarColorFromStatus(status: string, hover?: boolean): string {
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

export function getGraphColors(): Record<string, string | null> {
    return {
        axisLabel: '#333',
        axisLine: '#ddd',
        axis: '#999',
        crosshair: 'rgba(0,0,0,0.2)',
        tooltipBackground: '#1dc9b7',
        tooltipTitle: '#fff',
        tooltipBody: '#fff',
        annotationColor: null,
        annotationAccessoryColor: null,
    }
}
