import { useMemo } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { AppMetricColor, AppMetricsTrend } from './AppMetricsTrend'
import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export type AppMetricSummaryProps = {
    name: string
    color: AppMetricColor
    description: string
    timeSeries: AppMetricsTimeSeriesResponse | null
    previousPeriodTimeSeries?: AppMetricsTimeSeriesResponse | null
    loading?: boolean
}

export function AppMetricSummary({
    name,
    timeSeries,
    previousPeriodTimeSeries,
    color,
    description,
    loading,
}: AppMetricSummaryProps): JSX.Element {
    const total = useMemo(() => {
        if (!timeSeries) {
            return 0
        }
        return timeSeries.series.reduce((acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0), 0)
    }, [timeSeries])

    const totalPreviousPeriod = useMemo(() => {
        if (!previousPeriodTimeSeries) {
            return 0
        }
        return previousPeriodTimeSeries.series.reduce(
            (acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0),
            0
        )
    }, [previousPeriodTimeSeries])

    console.log(total, totalPreviousPeriod)

    return (
        <div className="flex flex-1 flex-col gap-2 relative border rounded p-3 bg-surface-primary min-w-[16rem] max-w-[24rem]">
            <div className="flex flex-row justify-between items-start">
                <LemonLabel info={description}>{name}</LemonLabel>
                <div className="text-right text-2xl text-muted-foreground">{humanFriendlyNumber(total)}</div>
            </div>

            <div className="flex-1">
                <AppMetricsTrend
                    timeSeries={timeSeries}
                    color={color}
                    loading={loading}
                    mode="compact"
                    className="h-[10rem]"
                />
            </div>
        </div>
    )
}
