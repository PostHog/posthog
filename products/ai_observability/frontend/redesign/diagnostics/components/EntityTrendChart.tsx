import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface EntityTrendChartProps {
    series: number[]
    /** The period of the same length before, bucket by bucket. Empty when the range has none. */
    previousSeries: number[]
    bucketStarts: string[]
    timezone: string
}

const PREVIOUS_DASH = [4, 4]

// A formatter called with more arguments would read the second one as a precision.
const formatCount = (value: number): string => humanFriendlyNumber(value)

export function EntityTrendChart({
    series,
    previousSeries,
    bucketStarts,
    timezone,
}: EntityTrendChartProps): JSX.Element {
    const theme = useChartTheme()
    const chartSeries = useMemo<Series[]>(
        () => [
            { key: 'current', label: 'This period', data: series },
            ...(previousSeries.length > 0
                ? [
                      {
                          key: 'previous',
                          label: 'Previous period',
                          data: previousSeries,
                          color: theme.axisColor,
                          stroke: { pattern: PREVIOUS_DASH },
                      },
                  ]
                : []),
        ],
        [series, previousSeries, theme.axisColor]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone },
            yAxis: { tickFormatter: formatCount, showGrid: true },
            tooltip: { valueFormatter: formatCount },
            legend: { show: previousSeries.length > 0, interactive: false, align: 'start' },
        }),
        [timezone, previousSeries.length]
    )
    return (
        <div className="relative flex h-48 flex-col">
            <TimeSeriesLineChart series={chartSeries} labels={bucketStarts} theme={theme} config={config} />
        </div>
    )
}
