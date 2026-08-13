import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    createXAxisTickCallback,
    type DateRangeZoomData,
    DefaultTooltip,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SparklineData } from './hogInvocationsLogic'

interface InvocationsSparklineProps {
    data: SparklineData | null
    loading: boolean
    onDateRangeChange: (dateFrom: string, dateTo: string | undefined) => void
}

export function InvocationsSparkline({
    data,
    loading,
    onDateRangeChange,
}: InvocationsSparklineProps): JSX.Element | null {
    const [collapsed, setCollapsed] = useState(false)

    const dates = useMemo(() => data?.dates ?? [], [data?.dates])

    const series = useMemo<Series[]>(
        () =>
            (data?.series ?? []).map((timeseries) => ({
                key: timeseries.name,
                label: timeseries.name,
                data: timeseries.values,
                color: getColorVar(timeseries.color),
            })),
        [data?.series]
    )

    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { tickFormatter: createXAxisTickCallback({ allDays: dates, timezone: dayjs.tz.guess() }) },
        }),
        [dates]
    )

    const onDateRangeZoom = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData): void => {
            const from = dates[startIndex]
            // +1 ends the range at the next bucket boundary; past the last bucket leaves dateTo
            // undefined, which the runs list reads as "up to now".
            const to = dates[endIndex + 1]
            if (from) {
                onDateRangeChange(from, to)
            }
        },
        [dates, onDateRangeChange]
    )

    const hasAnyData = (data?.series ?? []).some((s) => s.values.some((v) => v > 0))

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed(!collapsed)}
                    aria-expanded={!collapsed}
                >
                    <span className="text-xs text-muted">Volume over time</span>
                </LemonButton>
            </div>
            {!collapsed && (
                // Quill's chart root is flex-1, so the sized container has to be a flex column for h-24 to apply.
                <div className="relative h-24 flex flex-col">
                    {hasAnyData ? (
                        <TimeSeriesBarChart
                            series={series}
                            labels={dates}
                            theme={theme}
                            config={config}
                            onDateRangeZoom={onDateRangeZoom}
                            tooltip={(ctx) => (
                                <DefaultTooltip
                                    {...ctx}
                                    hideZeroRows
                                    sortedByValue
                                    valueFormatter={(value) => humanFriendlyNumber(value)}
                                    labelFormatter={(label) => dayjs(label).format('D MMM YYYY HH:mm')}
                                />
                            )}
                        />
                    ) : !loading ? (
                        <div className="h-full text-muted text-xs flex items-center justify-center">
                            No invocations in this window
                        </div>
                    ) : null}
                    {loading && <SpinnerOverlay />}
                </div>
            )}
        </div>
    )
}
