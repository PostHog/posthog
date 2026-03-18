import type { ChartConfig, ChartDataset, ChartScaleConfig } from './chartjs-mock'
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

function makeAxis(scaleConfig: ChartScaleConfig | undefined): Axis {
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

function resolveChartConfig(index: number): ChartConfig {
    const charts = getCapturedChartConfigs()
    if (charts.length === 0) {
        throw new Error('No charts captured')
    }
    const resolved = index < 0 ? charts.length + index : index
    if (resolved < 0 || resolved >= charts.length) {
        throw new Error(`No chart at index ${resolved} (${charts.length} captured)`)
    }
    return charts[resolved].config
}

function quotedSeriesNames(allSeries: Series[]): string[] {
    return allSeries.map((s) => `"${s.label}"`)
}

function findSeriesByName(allSeries: Series[], name: string): Series {
    const match = allSeries.find((s) => s.label === name)
    if (!match) {
        throw new Error(`No series "${name}". Available: ${quotedSeriesNames(allSeries).join(', ')}`)
    }
    return match
}

function findSeriesByIndex(allSeries: Series[], index: number): Series {
    if (index < 0 || index >= allSeries.length) {
        throw new Error(
            `Series index ${index} out of range (${allSeries.length} series: ${quotedSeriesNames(allSeries).join(', ')})`
        )
    }
    return allSeries[index]
}

function findSeries(allSeries: Series[], nameOrIndex: string | number): Series {
    return typeof nameOrIndex === 'number'
        ? findSeriesByIndex(allSeries, nameOrIndex)
        : findSeriesByName(allSeries, nameOrIndex)
}

function resolvePointIndex(labels: string[], pointIndexOrLabel: number | string): number {
    if (typeof pointIndexOrLabel === 'number') {
        return pointIndexOrLabel
    }
    const i = labels.indexOf(pointIndexOrLabel)
    if (i < 0) {
        throw new Error(`Label "${pointIndexOrLabel}" not found. Available: ${labels.map((l) => `"${l}"`).join(', ')}`)
    }
    return i
}

function labelAtIndex(labels: string[], index: number): string {
    if (index < 0 || index >= labels.length) {
        throw new Error(`Label index ${index} out of range (${labels.length} labels)`)
    }
    return labels[index]
}

/** Lazily creates axis accessors — x and y are pre-built, others are created on first access. */
function makeAxes(scales: Record<string, ChartScaleConfig | undefined>): Axes {
    return new Proxy(
        { x: makeAxis(scales.x), y: makeAxis(scales.y) },
        {
            get(target, prop) {
                if (typeof prop === 'string' && !(prop in target)) {
                    return makeAxis(scales[prop])
                }
                return target[prop as keyof typeof target]
            },
        }
    ) as Axes
}

export function getChart(index = -1): Chart {
    const config = resolveChartConfig(index)
    const allSeries = (config.data?.datasets ?? []).map(makeSeries)
    const chartLabels = config.data?.labels ?? []

    return {
        series: (nameOrIndex) => findSeries(allSeries, nameOrIndex),
        seriesCount: allSeries.length,
        seriesNames: allSeries.map((s) => s.label),
        value: (s, pointIndexOrLabel) => findSeries(allSeries, s).at(resolvePointIndex(chartLabels, pointIndexOrLabel)),
        labels: chartLabels,
        label: (i) => labelAtIndex(chartLabels, i),
        type: config.type ?? '',
        axes: makeAxes(config.options?.scales ?? {}),
        config,
    }
}
