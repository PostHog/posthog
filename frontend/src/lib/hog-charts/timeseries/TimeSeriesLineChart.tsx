import React from 'react'

import { LineChart } from '../charts/LineChart'
import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../core/types'

export interface TimeSeriesXAxis {
    /** Categorical labels — typically pre-formatted timestamps. Length must match each series.data. */
    labels: string[]
    tickFormatter?: (value: string, index: number) => string | null
    hide?: boolean
}

export interface TimeSeriesYAxis {
    /** `linear` (default) or `log`. Log falls back to a linear scale when no positive values exist. */
    scale?: 'linear' | 'log'
    tickFormatter?: (value: number) => string
    hide?: boolean
    showGrid?: boolean
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    xAxis: TimeSeriesXAxis
    yAxis?: TimeSeriesYAxis
    theme: ChartTheme
    /** `data-attr` applied to the chart wrapper for product-level test selectors. */
    dataAttr?: string
    className?: string
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    xAxis,
    yAxis,
    theme,
    dataAttr,
    className,
    tooltip,
    onPointClick,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const config: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter: xAxis.tickFormatter,
        yTickFormatter: yAxis?.tickFormatter,
        hideXAxis: xAxis.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
    }

    return (
        <LineChart
            series={series}
            labels={xAxis.labels}
            config={config}
            theme={theme}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        />
    )
}
