import React from 'react'

import { LineChart } from '../charts/LineChart'
import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../core/types'

export interface TimeSeriesLineChartConfig {
    xAxis?: {
        tickFormatter?: (value: string, index: number) => string | null
        hide?: boolean
    }
    yAxis?: {
        /** `linear` (default) or `log`. Log falls back to a linear scale when no positive values exist. */
        scale?: 'linear' | 'log'
        tickFormatter?: (value: number) => string
        hide?: boolean
        showGrid?: boolean
    }
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    /** Pre-formatted time labels. Length must match each series.data. */
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** `data-attr` applied to the chart wrapper for product-level test selectors. */
    dataAttr?: string
    className?: string
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    dataAttr,
    className,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const { xAxis, yAxis } = config ?? {}
    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter: xAxis?.tickFormatter,
        yTickFormatter: yAxis?.tickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
    }

    return (
        <LineChart
            series={series}
            labels={labels}
            config={lineChartConfig}
            theme={theme}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        />
    )
}
