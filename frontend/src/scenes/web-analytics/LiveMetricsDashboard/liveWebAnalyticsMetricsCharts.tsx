import { useMemo } from 'react'

import {
    DefaultTooltip,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    type TooltipContext,
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

// Buckets are minute-aligned absolute timestamps; labels stay ISO so the time axis formats them
// rather than printing baked display strings verbatim.
const useMinuteLabels = (data: ChartDataPoint[]): string[] =>
    useMemo(() => data.map((d) => dayjs(d.timestamp).toISOString()), [data])

export const UsersPerMinuteChart = ({ data, timezone }: { data: ChartDataPoint[]; timezone: string }): JSX.Element => {
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
            xAxis: { timezone, interval: 'minute' },
            yAxis: { format: 'short' },
            legend: { show: true },
        }),
        [timezone]
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
                        <DefaultTooltip
                            {...ctx}
                            labelFormatter={(label) =>
                                point
                                    ? `${point.minute} · ${point.users} visitors · ${point.pageviews} pageviews`
                                    : label
                            }
                        />
                    )
                }}
            />
        </div>
    )
}

export const BotEventsPerMinuteChart = ({
    data,
    timezone,
}: {
    data: ChartDataPoint[]
    timezone: string
}): JSX.Element => {
    const hasData = data.some((d) => d.botEvents > 0)
    const theme = useChartTheme()
    const labels = useMinuteLabels(data)

    const series = useMemo<Series[]>(
        () => [{ key: 'botEvents', label: 'Bot requests', data: data.map((d) => d.botEvents), color: BOT_COLOR }],
        [data]
    )

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { timezone, interval: 'minute' },
            yAxis: { format: 'short' },
        }),
        [timezone]
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
                        <DefaultTooltip
                            {...ctx}
                            labelFormatter={(label) =>
                                point ? `${point.minute} · ${point.botEvents} bot requests` : label
                            }
                        />
                    )
                }}
            />
        </div>
    )
}
