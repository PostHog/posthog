import { useMemo } from 'react'

import { TimeSeriesBarChart, TimeSeriesComboChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type {
    Series,
    TimeSeriesBarChartConfig,
    TimeSeriesComboChartConfig,
    TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { BillingPeriodMarkers } from './BillingPeriodMarkers'
import type { BillingPeriodMarker } from './BillingPeriodMarkers'
import { MAX_CHARTED_BILLING_SERIES } from './constants'
import type { BillingChartType } from './types'

export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    dates: string[]
}

export interface BillingChartProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
    interval?: 'day' | 'week' | 'month'
    billingPeriodMarkers?: BillingPeriodMarker[]
    /** Most series to draw. Beyond this the chart draws the largest and says what it left out. */
    maxSeries?: number
    /** Lines show each series' own shape; stacked bars show what the total is made of.
     *  Only pass 'bar' when the series share a unit - see canStackSeries in the logics. */
    chartType?: BillingChartType
    /** Draw the running total of the visible series across the range as a dashed line against a
     *  second, right-hand axis, named this in the tooltip. Spend passes it. Usage does not: a
     *  running total across products with different units means nothing. */
    cumulativeLabel?: string
}

const defaultFormatter = (value: number): string => value.toLocaleString()

const handleChartError = makeChartErrorHandler('billing-line-chart')

const NO_MARKERS: BillingPeriodMarker[] = []

/** Series keys are stringified ids, so a word cannot collide with one. */
const CUMULATIVE_KEY = 'cumulative'
const CUMULATIVE_AXIS_ID = 'cumulative'
/** Off the series palette, so it cannot be taken for one of the projects. */
const CUMULATIVE_COLOR = 'var(--text-3000)'

/** Per-period sum of the series, then a running sum across the range. */
export function runningTotal(series: BillingSeriesType[], periods: number): number[] {
    const perPeriod = new Array<number>(periods).fill(0)
    for (const s of series) {
        for (let i = 0; i < periods; i++) {
            perPeriod[i] += s.data[i] ?? 0
        }
    }
    let sum = 0
    return perPeriod.map((value) => (sum += value))
}

export function BillingChart({
    series,
    dates,
    isLoading,
    hiddenSeries,
    valueFormatter = defaultFormatter,
    showLegend = true,
    interval = 'day',
    billingPeriodMarkers = NO_MARKERS,
    maxSeries = MAX_CHARTED_BILLING_SERIES,
    chartType = 'line',
    cumulativeLabel,
}: BillingChartProps): JSX.Element {
    const theme = useChartTheme()

    // Drop hidden series rather than passing them with `visibility.excluded`. Neither caller
    // turns the legend on, and handing the chart every hidden series is most of the cost on an
    // organization with thousands of them.
    //
    // Color by series id, not by position after filtering: the ribbons in BillingDataTable are
    // keyed to the id, and the two have to agree.
    const { chartSeries, drawnCount, omittedCount } = useMemo<{
        chartSeries: Series[]
        drawnCount: number
        omittedCount: number
    }>(() => {
        const hidden = new Set(hiddenSeries)
        const visible = series.filter((s) => !hidden.has(s.id))
        const drawn =
            visible.length > maxSeries
                ? visible
                      .map((s) => ({ s, total: s.data.reduce((sum, value) => sum + value, 0) }))
                      .sort((a, b) => b.total - a.total)
                      .slice(0, maxSeries)
                      .map(({ s }) => s)
                : visible

        const chartSeries: Series[] = drawn.map((s) => ({
            key: String(s.id),
            label: s.label,
            data: s.data,
            color: getSeriesColor(s.id),
        }))

        if (cumulativeLabel) {
            // Summed over every visible series, not only the drawn ones, so the draw cap does not
            // reduce the total.
            chartSeries.push({
                key: CUMULATIVE_KEY,
                label: cumulativeLabel,
                data: runningTotal(visible, dates.length),
                color: CUMULATIVE_COLOR,
                type: 'line',
                yAxisId: CUMULATIVE_AXIS_ID,
                stroke: { pattern: [6, 4] },
                // The running total is not part of any one period, so the tooltip total leaves it out.
                visibility: { total: false },
            })
        }

        return { chartSeries, drawnCount: drawn.length, omittedCount: visible.length - drawn.length }
    }, [series, hiddenSeries, maxSeries, cumulativeLabel, dates.length])

    // The chart types take the same axis, legend and tooltip options, so the shared shape is
    // built once and each config below only adds what is its own.
    const shared = {
        xAxis: { timezone: 'UTC' as const, interval },
        yAxis: { tickFormatter: valueFormatter },
        legend: { show: showLegend, position: 'bottom' as const, interactive: false },
        tooltip: { sortedByValue: true, valueFormatter, placement: 'cursor' as const },
    }

    const lineConfig = useChartConfig<TimeSeriesLineChartConfig>(() => shared, [interval, valueFormatter, showLegend])

    const barConfig = useChartConfig<TimeSeriesBarChartConfig>(
        // Stacked, which is the point of offering bars: the height is the total and the segments
        // are its parts. It is quill's default too, set explicitly here.
        () => ({ ...shared, barLayout: 'stacked' as const }),
        [interval, valueFormatter, showLegend]
    )

    const comboConfig = useChartConfig<TimeSeriesComboChartConfig>(
        () => ({
            ...shared,
            // The running total ends up many periods tall. On the series' own axis it would
            // flatten every bar and line under it, so it gets an axis of its own on the right.
            yAxis: [
                { id: 'left', tickFormatter: valueFormatter },
                { id: CUMULATIVE_AXIS_ID, position: 'right' as const, tickFormatter: valueFormatter },
            ],
            defaultSeriesType: chartType,
            barLayout: 'stacked' as const,
        }),
        [interval, valueFormatter, showLegend, chartType]
    )

    // The billing period label is anchored above the plot, so it sits outside the chart
    // wrapper's box and would otherwise be cut off by its `overflow-hidden`.
    const chartProps = {
        series: chartSeries,
        labels: dates,
        theme,
        onError: handleChartError,
        className: 'overflow-visible!',
    }
    const markers = <BillingPeriodMarkers markers={billingPeriodMarkers} />
    const dataAttr = chartType === 'bar' ? 'billing-chart-bar' : 'billing-chart-line'

    return (
        <>
            {/* pt-8 reserves room above the plot for the billing period label, which sits outside the
                plot area so that hovering it takes the cursor out of the chart's hover region. */}
            <div className="relative flex flex-col h-96 pt-8">
                {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-bg-light bg-opacity-75 z-10">
                        <div className="text-muted">Loading...</div>
                    </div>
                )}
                {cumulativeLabel ? (
                    // Only a chart with a running total mixes a line with bars; without one the single-type
                    // charts are used.
                    <TimeSeriesComboChart dataAttr={dataAttr} {...chartProps} config={comboConfig}>
                        {markers}
                    </TimeSeriesComboChart>
                ) : chartType === 'bar' ? (
                    <TimeSeriesBarChart dataAttr={dataAttr} {...chartProps} config={barConfig}>
                        {markers}
                    </TimeSeriesBarChart>
                ) : (
                    <TimeSeriesLineChart dataAttr={dataAttr} {...chartProps} config={lineConfig}>
                        {markers}
                    </TimeSeriesLineChart>
                )}
            </div>
            {cumulativeLabel && (
                // Neither caller shows a legend, so the dashed line has to be named somewhere.
                <div className="mt-1 text-xs text-secondary" data-attr="billing-chart-cumulative-note">
                    Dashed line: {cumulativeLabel.toLowerCase()} across the selected range, against the right-hand axis.
                </div>
            )}
            {omittedCount > 0 && (
                <div className="mt-1 text-xs text-secondary" data-attr="billing-chart-series-cap">
                    Charting the {drawnCount.toLocaleString()} largest series. {omittedCount.toLocaleString()} more are
                    in the table below and in the CSV export.
                </div>
            )}
        </>
    )
}
