import { useMemo } from 'react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AISpendResponseApi } from 'products/billing/frontend/generated/api.schemas'

import { ChartedProduct, periodDates } from './aiSpend'

const handleChartError = makeChartErrorHandler('ai-credits-daily-spend')

const formatDollars = (value: number): string => humanFriendlyCurrency(value, 0)
const formatSpend = (value: number): string => humanFriendlyCurrency(value)

export interface DailySpendChartProps {
    spend: AISpendResponseApi
    products: ChartedProduct[]
}

export function DailySpendChart({ spend, products }: DailySpendChartProps): JSX.Element {
    const theme = useChartTheme()
    const charted = useMemo(() => products.filter((product) => product.share > 0), [products])

    const dates = useMemo(() => periodDates(spend), [spend])
    const series = useMemo<Series[]>(() => {
        const byDate = new Map(spend.days.map((day) => [day.date, day.spend_usd]))
        const today = dayjs.utc().format('YYYY-MM-DD')
        return charted.map((product) => ({
            key: product.product,
            label: product.name,
            color: product.color,
            // Days still to come have no value yet, so they draw nothing rather than a zero.
            data: dates.map((date) => {
                const value = byDate.get(date)?.[product.product]
                return value !== undefined ? Number(value) : date <= today ? 0 : NaN
            }),
        }))
    }, [spend, charted, dates])

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { timezone: 'UTC', interval: 'day' },
            yAxis: { tickFormatter: formatDollars, showGrid: true },
            barLayout: 'stacked',
            barCornerRadius: 2,
            tooltip: { valueFormatter: formatSpend, sortedByValue: true, hideZeroRows: true, showTotal: true },
        }),
        []
    )

    return (
        <div className="flex flex-col gap-3 rounded border bg-surface-primary px-5 pt-4 pb-3">
            <h3 className="m-0 text-base font-semibold">Daily spend by product</h3>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
                {charted.map((product) => (
                    <span key={product.product} className="flex items-center gap-1.5 text-xs text-secondary">
                        {/* The swatch takes the product's chart color, which no utility class can hold. */}
                        <span className="size-2.5 shrink-0 rounded-xs" style={{ backgroundColor: product.color }} />
                        {product.name}
                        <span className="text-tertiary">{Math.round(product.share * 100)}%</span>
                    </span>
                ))}
            </div>
            <div className="flex h-2 gap-0.5 overflow-hidden rounded-xs">
                {charted.map((product) => (
                    <div
                        key={product.product}
                        // Each segment's width is the product's share of spend, and its color the product's.
                        style={{ width: `${product.share * 100}%`, backgroundColor: product.color }}
                    />
                ))}
            </div>
            <div className="flex h-48 flex-col">
                <TimeSeriesBarChart
                    series={series}
                    labels={dates}
                    theme={theme}
                    config={config}
                    onError={handleChartError}
                    dataAttr="ai-credits-daily-spend-chart"
                />
            </div>
        </div>
    )
}
