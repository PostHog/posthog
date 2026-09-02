import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { BillingPeriodMarkers } from './BillingPeriodMarkers'
import type { BillingPeriodMarker } from './BillingPeriodMarkers'

export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    dates: string[]
}

export interface BillingLineGraphProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
    interval?: 'day' | 'week' | 'month'
    billingPeriodMarkers?: BillingPeriodMarker[]
}

const defaultFormatter = (value: number): string => value.toLocaleString()

const handleChartError = makeChartErrorHandler('billing-line-chart')

const NO_MARKERS: BillingPeriodMarker[] = []

export function BillingLineGraph({
    series,
    dates,
    isLoading,
    hiddenSeries,
    valueFormatter = defaultFormatter,
    showLegend = true,
    interval = 'day',
    billingPeriodMarkers = NO_MARKERS,
}: BillingLineGraphProps): JSX.Element {
    const theme = useChartTheme()

    // Hide via `visibility.excluded` rather than by filtering the array, so a hidden series stays
    // listed (dimmed) if the legend is ever turned on. Color by series id, not by position: the
    // ribbons in BillingDataTable are keyed to the id, and the two have to agree.
    const chartSeries = useMemo<Series[]>(
        () =>
            series.map((s) => ({
                key: String(s.id),
                label: s.label,
                data: s.data,
                color: getSeriesColor(s.id),
                visibility: { excluded: hiddenSeries.includes(s.id) },
            })),
        [series, hiddenSeries]
    )

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone: 'UTC', interval },
            yAxis: { tickFormatter: valueFormatter },
            legend: { show: showLegend, position: 'bottom', interactive: false },
            tooltip: { sortedByValue: true, valueFormatter, placement: 'cursor' },
        }),
        [interval, valueFormatter, showLegend]
    )

    return (
        // pt-8 reserves room above the plot for the billing period label, which sits outside the plot
        // area so that hovering it takes the cursor out of the chart's hover region.
        <div className="relative flex flex-col h-96 pt-8">
            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-bg-light bg-opacity-75 z-10">
                    <div className="text-muted">Loading...</div>
                </div>
            )}
            <TimeSeriesLineChart
                series={chartSeries}
                labels={dates}
                theme={theme}
                config={config}
                onError={handleChartError}
                // The billing period label is anchored above the plot, so it sits outside the chart
                // wrapper's box and would otherwise be cut off by its `overflow-hidden`.
                className="overflow-visible!"
            >
                <BillingPeriodMarkers markers={billingPeriodMarkers} />
            </TimeSeriesLineChart>
        </div>
    )
}
