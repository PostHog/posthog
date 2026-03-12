import type { ChartConfig, ChartDataset } from './chartjs-mock'
import { getCapturedChartConfigs } from './chartjs-mock'

interface Series {
    label: string
    data: number[]
    at(index: number): number
    hidden: boolean
    borderColor: string
    backgroundColor: string
}

function makeSeries(ds: ChartDataset): Series {
    const data = ds.data ?? []
    return {
        label: ds.label ?? '',
        data,
        at(index: number): number {
            if (index < 0 || index >= data.length) {
                throw new Error(`Point index ${index} out of range (series "${ds.label}" has ${data.length} points)`)
            }
            return data[index]
        },
        hidden: ds.hidden ?? false,
        borderColor: ds.borderColor ?? '',
        backgroundColor: ds.backgroundColor ?? '',
    }
}

interface Axis {
    display: boolean
    type: string
    stacked: boolean
    position: string
    tickLabel: (value: number | string) => string
}

interface Axes {
    [key: string]: Axis
    x: Axis
    y: Axis
}

interface ScaleConfig {
    display?: boolean
    type?: string
    stacked?: boolean
    position?: string
    ticks?: { callback?: (value: number | string, index: number, values: unknown[]) => string }
}

function makeAxis(scaleConfig: ScaleConfig | undefined): Axis {
    return {
        display: scaleConfig?.display ?? true,
        type: scaleConfig?.type ?? 'linear',
        stacked: scaleConfig?.stacked ?? false,
        position: scaleConfig?.position ?? 'left',
        tickLabel: (value: number | string) => {
            const cb = scaleConfig?.ticks?.callback
            return typeof cb === 'function' ? String(cb(value, 0, [])) : String(value)
        },
    }
}

export interface Chart {
    series(nameOrIndex: string | number): Series
    seriesCount: number
    seriesNames: string[]
    value(series: string | number, pointIndexOrLabel: number | string): number
    labels: string[]
    label(index: number): string
    type: string
    axes: Axes
    config: ChartConfig
}

export function getChart(index = -1): Chart {
    const charts = getCapturedChartConfigs()
    if (charts.length === 0) {
        throw new Error('No charts captured')
    }
    const resolvedIndex = index < 0 ? charts.length + index : index
    if (resolvedIndex < 0 || resolvedIndex >= charts.length) {
        throw new Error(`No chart at index ${resolvedIndex} (${charts.length} captured)`)
    }
    const { config } = charts[resolvedIndex]
    const allSeries = (config.data?.datasets ?? []).map(makeSeries)
    const scales = config.options?.scales ?? {}

    const axes = new Proxy(
        {
            x: makeAxis(scales.x),
            y: makeAxis(scales.y),
        },
        {
            get(target, prop) {
                if (typeof prop === 'string' && !(prop in target)) {
                    return makeAxis(scales[prop])
                }
                return target[prop as keyof typeof target]
            },
        }
    ) as Axes

    const chartLabels = config.data?.labels ?? []

    function findSeries(nameOrIndex: string | number): Series {
        if (typeof nameOrIndex === 'number') {
            if (nameOrIndex < 0 || nameOrIndex >= allSeries.length) {
                throw new Error(
                    `Series index ${nameOrIndex} out of range (${allSeries.length} series: ${allSeries.map((s) => `"${s.label}"`).join(', ')})`
                )
            }
            return allSeries[nameOrIndex]
        }
        const match = allSeries.find((s) => s.label === nameOrIndex)
        if (!match) {
            throw new Error(`No series "${nameOrIndex}". Available: ${allSeries.map((s) => `"${s.label}"`).join(', ')}`)
        }
        return match
    }

    return {
        series: findSeries,
        seriesCount: allSeries.length,
        seriesNames: allSeries.map((s) => s.label),
        value: (s, pointIndexOrLabel) => {
            const i = typeof pointIndexOrLabel === 'string' ? chartLabels.indexOf(pointIndexOrLabel) : pointIndexOrLabel
            if (i < 0) {
                throw new Error(
                    `Label "${pointIndexOrLabel}" not found. Available: ${chartLabels.map((l) => `"${l}"`).join(', ')}`
                )
            }
            return findSeries(s).at(i)
        },
        labels: chartLabels,
        label: (i) => {
            if (i < 0 || i >= chartLabels.length) {
                throw new Error(`Label index ${i} out of range (${chartLabels.length} labels)`)
            }
            return chartLabels[i]
        },
        type: config.type ?? '',
        axes,
        config,
    }
}
