import { hexToRGB } from 'lib/utils'

import { HeatmapGradientStop } from '~/queries/schema/schema-general'

const DEFAULT_GRADIENT_COLORS = ['#E2E8F0', '#2563EB']
const DEFAULT_GRADIENT_STOPS: HeatmapGradientStop[] = [
    { value: 0, color: DEFAULT_GRADIENT_COLORS[0] },
    { value: 1, color: DEFAULT_GRADIENT_COLORS[1] },
]

const buildGradientStops = (colors: string[]): HeatmapGradientStop[] => {
    if (colors.length === 1) {
        return [{ value: 0, color: colors[0] }]
    }

    return colors.map((color, index) => ({
        value: index / (colors.length - 1),
        color,
    }))
}

export const HEATMAP_GRADIENT_PRESETS = [
    {
        value: 'viridis',
        label: 'Viridis',
        stops: buildGradientStops(['#440154', '#3B528B', '#21918C', '#5DC863', '#FDE725']),
    },
    {
        value: 'plasma',
        label: 'Plasma',
        stops: buildGradientStops(['#0D0887', '#7E03A8', '#CC4778', '#F89441', '#F0F921']),
    },
    {
        value: 'inferno',
        label: 'Inferno',
        stops: buildGradientStops(['#000004', '#420A68', '#932667', '#DD513A', '#FDE724']),
    },
    {
        value: 'magma',
        label: 'Magma',
        stops: buildGradientStops(['#000004', '#3B0F70', '#8C2981', '#DE4968', '#FE9F6D', '#FCFDBF']),
    },
    {
        value: 'cividis',
        label: 'Cividis',
        stops: buildGradientStops(['#00204C', '#2E4A7D', '#7E8F6A', '#C6BE5E', '#FDE945']),
    },
    {
        value: 'turbo',
        label: 'Turbo',
        stops: buildGradientStops(['#30123B', '#4145AB', '#2FB47C', '#FDE725']),
    },
    {
        value: 'blues',
        label: 'Blues',
        stops: buildGradientStops(['#F7FBFF', '#DEEBF7', '#9ECAE1', '#4292C6', '#08519C']),
    },
    {
        value: 'greens',
        label: 'Greens',
        stops: buildGradientStops(['#F7FCF5', '#E5F5E0', '#A1D99B', '#41AB5D', '#005A32']),
    },
    {
        value: 'reds',
        label: 'Reds',
        stops: buildGradientStops(['#FFF5F0', '#FEE0D2', '#FC9272', '#DE2D26', '#A50F15']),
    },
    {
        value: 'purples',
        label: 'Purples',
        stops: buildGradientStops(['#FCFBFD', '#E7E1EF', '#C994C7', '#9E9AC8', '#4A1486']),
    },
    {
        value: 'greys',
        label: 'Greys',
        stops: buildGradientStops(['#FFFFFF', '#F0F0F0', '#BDBDBD', '#636363', '#252525']),
    },
    {
        value: 'spectral',
        label: 'Spectral',
        stops: buildGradientStops(['#9E0142', '#D53E4F', '#F46D43', '#FEE08B', '#E6F598', '#66C2A5', '#3288BD']),
    },
] as const

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

export const stretchGradientStopsToValues = (stops: HeatmapGradientStop[], values: number[]): HeatmapGradientStop[] => {
    if (values.length === 0) {
        return stops
    }

    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)

    if (minValue === maxValue) {
        return sortGradientStops(stops).map((stop) => ({ ...stop, value: minValue }))
    }

    const sortedStops = sortGradientStops(stops)
    const minStop = sortedStops[0]?.value ?? 0
    const maxStop = sortedStops[sortedStops.length - 1]?.value ?? 1

    if (minStop === maxStop) {
        return sortedStops.map((stop) => ({ ...stop, value: minValue }))
    }

    return sortedStops.map((stop) => ({
        ...stop,
        value: minValue + ((stop.value - minStop) / (maxStop - minStop)) * (maxValue - minValue),
    }))
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

    const upperIndex = sortedStops.findIndex((stop) => value <= stop.value)
    const resolvedUpperIndex = upperIndex === -1 ? sortedStops.length - 1 : upperIndex
    const resolvedLowerIndex = Math.max(0, resolvedUpperIndex - 1)

    const lowerStop = sortedStops[resolvedLowerIndex]
    const upperStop = sortedStops[resolvedUpperIndex]

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
