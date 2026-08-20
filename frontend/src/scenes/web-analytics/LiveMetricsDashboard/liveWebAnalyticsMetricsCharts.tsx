import { useMemo } from 'react'

import {
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    type TooltipContext,
    TooltipSurface,
    TooltipSwatch,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'

import { ChartDataPoint } from './LiveWebAnalyticsMetricsTypes'

// Tailwind green-500 / blue-500 / red-500 — new visitors, returning visitors, bots.
const NEW_USERS_COLOR = '#22c55e'
const RETURNING_USERS_COLOR = '#3b82f6'
const BOT_COLOR = '#ef4444'

const EmptyState = ({ message }: { message: string }): JSX.Element => (
    <div className="h-full flex items-center justify-center text-muted text-sm">{message}</div>
)

// Buckets are minute-aligned absolute timestamps; labels stay ISO so the time axis and tooltip
// header format them (in the viewer's local zone, matching the "shown in your local timezone" note)
// rather than baking display strings the axis would print verbatim.
const useMinuteLabels = (data: ChartDataPoint[]): string[] =>
    useMemo(() => data.map((d) => dayjs(d.timestamp).toISOString()), [data])

const TooltipRow = ({ color, label, value }: { color: string; label: string; value: number }): JSX.Element => (
    <div className="flex items-center justify-between gap-4">
        <span className="flex items-center gap-1.5">
            <TooltipSwatch color={color} />
            <span className="opacity-60">{label}</span>
        </span>
        <strong className="tabular-nums">{value.toLocaleString()}</strong>
    </div>
)

export const UsersPerMinuteChart = ({ data }: { data: ChartDataPoint[] }): JSX.Element => {
    const hasData = data.some((d) => d.users > 0)
    const theme = useChartTheme()
    const labels = useMinuteLabels(data)

    const series = useMemo<Series[]>(
        () => [
            { key: 'newUsers', label: 'New visitors', data: data.map((d) => d.newUsers), color: NEW_USERS_COLOR },
            {
                key: 'returningUsers',
                label: 'Returning visitors',
                data: data.map((d) => d.returningUsers),
                color: RETURNING_USERS_COLOR,
            },
        ],
        [data]
    )

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'stacked',
            xAxis: { tickFormatter: (label) => dayjs(label).format('HH:mm') },
            yAxis: { format: 'short' },
            legend: { show: true, position: 'top', align: 'end' },
        }),
        []
    )

    if (!hasData) {
        return <EmptyState message="No activity in the last 30 minutes" />
    }

    return (
        <div className="h-full flex flex-col">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={(ctx: TooltipContext) => {
                    const point = data[ctx.dataIndex]
                    return (
                        <TooltipSurface>
                            <div className="font-semibold mb-1">
                                {point
                                    ? `${point.minute} · ${point.users} visitors · ${point.pageviews} pageviews`
                                    : ctx.label}
                            </div>
                            {ctx.seriesData.map((entry) => (
                                <TooltipRow
                                    key={entry.series.key}
                                    color={entry.color}
                                    label={entry.series.label}
                                    value={entry.value}
                                />
                            ))}
                        </TooltipSurface>
                    )
                }}
            />
        </div>
    )
}

export const BotEventsPerMinuteChart = ({ data }: { data: ChartDataPoint[] }): JSX.Element => {
    const hasData = data.some((d) => d.botEvents > 0)
    const theme = useChartTheme()
    const labels = useMinuteLabels(data)

    const series = useMemo<Series[]>(
        () => [{ key: 'botEvents', label: 'Bot requests', data: data.map((d) => d.botEvents), color: BOT_COLOR }],
        [data]
    )

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { tickFormatter: (label) => dayjs(label).format('HH:mm') },
            yAxis: { format: 'short' },
        }),
        []
    )

    if (!hasData) {
        return <EmptyState message="No bots detected in the last 30 minutes" />
    }

    return (
        <div className="h-full flex flex-col">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={(ctx: TooltipContext) => {
                    const point = data[ctx.dataIndex]
                    return (
                        <TooltipSurface>
                            <div className="font-semibold mb-1">
                                {point ? `${point.minute} · ${point.botEvents} bot requests` : ctx.label}
                            </div>
                            {ctx.seriesData.map((entry) => (
                                <TooltipRow
                                    key={entry.series.key}
                                    color={entry.color}
                                    label={entry.series.label}
                                    value={entry.value}
                                />
                            ))}
                        </TooltipSurface>
                    )
                }}
            />
        </div>
    )
}
