import './BillingLineGraph.scss'

import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { BillingPeriodMarkers } from './BillingPeriodMarkers'
import type { BillingPeriodMarker } from './BillingPeriodMarkers'

export type { BillingPeriodMarker }

export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    dates: string[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
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

export function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    return <div className={`series-color-dot series-color-dot-${colorIndex % 15}`} />
}

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

    // Color by series id, not by position: hiding a series shifts positions but the ribbons in
    // BillingDataTable stay keyed to the id, and the two have to agree.
    const chartSeries = useMemo<Series[]>(
        () =>
            series
                .filter((s) => !hiddenSeries.includes(s.id))
                .map((s) => ({
                    key: String(s.id),
                    label: s.label,
                    data: s.data,
                    color: getSeriesColor(s.id % 15),
                })),
        [series, hiddenSeries]
    )

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone: 'UTC', interval },
            yAxis: { tickFormatter: valueFormatter },
            legend: { show: showLegend, position: 'bottom', interactive: false },
            tooltip: { sortedByValue: true, valueFormatter: (value: number) => valueFormatter(value) },
        }),
        [interval, valueFormatter, showLegend]
    )

    return (
        <div className="relative flex flex-col h-96">
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
            >
                <BillingPeriodMarkers markers={billingPeriodMarkers} />
            </TimeSeriesLineChart>
        </div>
    )
}
