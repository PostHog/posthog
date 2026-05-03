import React from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { LineChart } from '../LineChart'
import { useXTickFormatter, useYTickFormatter, type XAxisConfig, type YAxisConfig } from './utils/use-axis-formatters'

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
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
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
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
