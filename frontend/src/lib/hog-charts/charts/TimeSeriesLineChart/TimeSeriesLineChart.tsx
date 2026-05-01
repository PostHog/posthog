import React from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { LineChart } from '../LineChart'
import { createXAxisTickCallback, type TimeInterval } from './utils/dates'

export interface TimeSeriesLineChartConfig {
    xAxis?: {
        /** Custom tick label formatter. When set, it wins over the date-axis auto formatter. */
        tickFormatter?: (value: string, index: number) => string | null
        hide?: boolean
        /** IANA timezone (e.g. `UTC`, `America/New_York`) for date-axis tick formatting.
         * Combined with `interval`, enables auto-formatting via `createXAxisTickCallback`. */
        timezone?: string
        /** Bucket size of the X axis. Combined with `timezone`, enables auto-formatting. */
        interval?: TimeInterval
        /** Resolved date range of the chart. Reserved for future date-axis behavior. */
        dateRange?: { start: string; end: string }
        /** The raw date strings underlying each label, used to compute boundary-aware ticks.
         * If omitted, falls back to `labels`. */
        allDays?: string[]
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
    const xTickFormatter =
        xAxis?.tickFormatter ??
        (xAxis?.timezone && xAxis?.interval
            ? createXAxisTickCallback({
                  timezone: xAxis.timezone,
                  interval: xAxis.interval,
                  allDays: xAxis.allDays ?? labels,
              })
            : undefined)
    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
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
