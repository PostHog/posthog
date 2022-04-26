/* Insight series colors. */
const dataColorVars = [
    'data-lilac',
    'data-orange',
    'data-blue',
    'data-green',
    'data-vermilion',
    'data-spruce',
    'data-magenta',
    'data-brown',
    'data-orchid',
    'data-purple',
    'data-teal',
    'data-grape',
    'data-yellow',
    'data-aquamarine',
    'data-pink',
    'data-mint',
    'data-olivine',
    'data-tan',
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

/** @deprecated
 * Return an array of hexadecimal series color values. Use getSeriesColor() directly instead.
 *
 * Hexadecimal format as Chart.js doesn't work with CSS vars.
 */
export function getChartColors(numSeries?: number, injectLightColors: boolean = false): string[] {
    const colors: string[] = []
    for (let i = 0; i < (numSeries ?? dataColorVars.length); i++) {
        const hex = getColorVar(dataColorVars[i % dataColorVars.length])
        colors.push(hex)
        if (injectLightColors) {
            colors.push(`${hex}80`)
        }
    }
    return colors
}

export function getSeriesColor(index?: number, fallbackColor?: string, numSeries?: number): string {
    if (typeof index === 'number' && index >= 0) {
        return getChartColors(numSeries)[index]
    }
    return fallbackColor ?? getChartColors()[0]
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
