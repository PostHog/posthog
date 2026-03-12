import type { ChartConfig, ChartDataset } from './chartjs-mock'
import { getCapturedChartConfigs } from './chartjs-mock'

interface DatasetAccessor {
    [index: number]: number
    label: string
    data: number[]
    hidden: boolean
    borderColor: string
    backgroundColor: string
    yAxisID: string
    length: number
}

interface AxisAccessor {
    display: boolean
    type: string
    stacked: boolean
    tickLabel: (value: number | string) => string
    position: string
}

interface AxesAccessor {
    [key: string]: AxisAccessor
    x: AxisAccessor
    y: AxisAccessor
}

interface ScaleConfig {
    display?: boolean
    type?: string
    stacked?: boolean
    position?: string
    ticks?: { callback?: (value: number | string, index: number, values: unknown[]) => string }
}

interface ChartAccessor {
    datasets: DatasetAccessor[]
    labels: string[]
    axes: AxesAccessor
    type: string
    options: ChartConfig['options']
    config: ChartConfig
}

function makeAxisAccessor(scaleConfig: ScaleConfig | undefined): AxisAccessor {
    return {
        display: scaleConfig?.display ?? true,
        type: scaleConfig?.type ?? 'linear',
        stacked: scaleConfig?.stacked ?? false,
        position: scaleConfig?.position ?? 'left',
        tickLabel: (value: number | string) => {
            const cb = scaleConfig?.ticks?.callback
            if (typeof cb === 'function') {
                return String(cb(value, 0, []))
            }
            return String(value)
        },
    }
}

function makeDatasetAccessor(ds: ChartDataset): DatasetAccessor {
    const data: number[] = ds.data ?? []

    return new Proxy(
        {
            label: ds.label ?? '',
            data,
            hidden: ds.hidden ?? false,
            borderColor: ds.borderColor ?? '',
            backgroundColor: ds.backgroundColor ?? '',
            yAxisID: ds.yAxisID ?? 'y',
            length: data.length,
        },
        {
            get(target, prop) {
                if (typeof prop === 'string' && /^\d+$/.test(prop)) {
                    return data[Number(prop)]
                }
                return target[prop as keyof typeof target]
            },
        }
    ) as DatasetAccessor
}

export function getChart(index = -1): ChartAccessor {
    const charts = getCapturedChartConfigs()
    if (charts.length === 0) {
        throw new Error('No charts captured')
    }
    const resolvedIndex = index < 0 ? charts.length + index : index
    if (resolvedIndex < 0 || resolvedIndex >= charts.length) {
        throw new Error(`No chart at index ${resolvedIndex} (${charts.length} captured)`)
    }
    const { config } = charts[resolvedIndex]
    const scales = config.options?.scales ?? {}

    const axes = new Proxy(
        {
            x: makeAxisAccessor(scales.x),
            y: makeAxisAccessor(scales.y),
        },
        {
            get(target, prop) {
                if (typeof prop === 'string' && !(prop in target)) {
                    return makeAxisAccessor(scales[prop])
                }
                return target[prop as keyof typeof target]
            },
        }
    ) as AxesAccessor

    return {
        datasets: (config.data?.datasets ?? []).map(makeDatasetAccessor),
        labels: config.data?.labels ?? [],
        axes,
        type: config.type ?? '',
        options: config.options ?? {},
        config,
    }
}
