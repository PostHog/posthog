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

interface ChartAccessor {
    datasets: DatasetAccessor[]
    labels: string[]
    axes: AxesAccessor
    type: string
    options: any
    config: any
}

function makeAxisAccessor(scaleConfig: any): AxisAccessor {
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

function makeDatasetAccessor(ds: any): DatasetAccessor {
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
                return (target as any)[prop]
            },
        }
    ) as DatasetAccessor
}

export function getChart(index = 0): ChartAccessor {
    const charts = getCapturedChartConfigs()
    if (index >= charts.length) {
        throw new Error(`No chart at index ${index} (${charts.length} captured)`)
    }
    const { config } = charts[index]
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
                return (target as any)[prop]
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
