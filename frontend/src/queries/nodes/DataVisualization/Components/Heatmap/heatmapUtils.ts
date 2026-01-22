import { hexToRGB } from 'lib/utils'

import { HeatmapGradientStop } from '~/queries/schema/schema-general'

const DEFAULT_GRADIENT_COLORS = ['#E2E8F0', '#2563EB']
const DEFAULT_GRADIENT_STOPS: HeatmapGradientStop[] = [
    { value: 0, color: DEFAULT_GRADIENT_COLORS[0] },
    { value: 1, color: DEFAULT_GRADIENT_COLORS[1] },
]

const toHex = (value: number): string => value.toString(16).padStart(2, '0')

export const sortGradientStops = (stops: HeatmapGradientStop[]): HeatmapGradientStop[] => {
    return [...stops].sort((a, b) => a.value - b.value)
}

export const resolveGradientStops = (
    stops: HeatmapGradientStop[] | undefined,
    fallbackStops: HeatmapGradientStop[] = DEFAULT_GRADIENT_STOPS
): HeatmapGradientStop[] => {
    if (stops && stops.length > 0) {
        return sortGradientStops(stops)
    }
    return sortGradientStops(fallbackStops)
}

export const buildFallbackGradientStops = (values: number[]): HeatmapGradientStop[] => {
    if (values.length === 0) {
        return DEFAULT_GRADIENT_STOPS
    }

    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)

    if (minValue === maxValue) {
        return [
            { value: minValue, color: DEFAULT_GRADIENT_COLORS[0] },
            { value: maxValue + 1, color: DEFAULT_GRADIENT_COLORS[1] },
        ]
    }

    return [
        { value: minValue, color: DEFAULT_GRADIENT_COLORS[0] },
        { value: maxValue, color: DEFAULT_GRADIENT_COLORS[1] },
    ]
}

export const interpolateHeatmapColor = (value: number, stops: HeatmapGradientStop[]): string => {
    if (stops.length === 0) {
        return 'transparent'
    }

    const sortedStops = sortGradientStops(stops)

    if (value <= sortedStops[0].value) {
        return sortedStops[0].color
    }

    const lastStop = sortedStops[sortedStops.length - 1]
    if (value >= lastStop.value) {
        return lastStop.color
    }

    const lowerIndex = sortedStops.findIndex((stop, index) => {
        const nextStop = sortedStops[index + 1]
        return nextStop ? value >= stop.value && value <= nextStop.value : false
    })

    const lowerStop = sortedStops[Math.max(0, lowerIndex)]
    const upperStop = sortedStops[Math.min(sortedStops.length - 1, lowerIndex + 1)]

    if (upperStop.value === lowerStop.value) {
        return upperStop.color
    }

    const ratio = (value - lowerStop.value) / (upperStop.value - lowerStop.value)
    const lowerColor = hexToRGB(lowerStop.color)
    const upperColor = hexToRGB(upperStop.color)

    const r = Math.round(lowerColor.r + (upperColor.r - lowerColor.r) * ratio)
    const g = Math.round(lowerColor.g + (upperColor.g - lowerColor.g) * ratio)
    const b = Math.round(lowerColor.b + (upperColor.b - lowerColor.b) * ratio)

    return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

export const getHeatmapTextClassName = (color: string): string => {
    const { r, g, b } = hexToRGB(color)
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 140 ? 'text-white' : 'text-primary'
}
