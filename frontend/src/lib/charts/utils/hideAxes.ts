import type { XAxisConfig, YAxisConfig } from '@posthog/quill-charts'

interface TimeSeriesAxesConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig | YAxisConfig[]
}

export function withHiddenAxes<T extends TimeSeriesAxesConfig>(config: T, hide: boolean | undefined): T {
    if (!hide) {
        return config
    }
    const yAxis = Array.isArray(config.yAxis)
        ? config.yAxis.map((axis) => ({ ...axis, hide: true }))
        : { ...config.yAxis, hide: true }
    return { ...config, xAxis: { ...config.xAxis, hide: true }, yAxis }
}
