import { useMemo } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonLabel, LemonSkeleton, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { formatPercentageDiff, humanFriendlyNumber } from 'lib/utils/numbers'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'
import { AppMetricsSeriesOverride, AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

export type AppMetricSummaryProps = {
    name: string
    description: string
    color?: string
    colorIfZero?: string
    timeSeries: AppMetricsTimeSeriesResponse | null
    previousPeriodTimeSeries?: AppMetricsTimeSeriesResponse | null
    loading?: boolean
    hideIfZero?: boolean
    /** When set, the tile becomes clickable (e.g. to drill into matching invocations). */
    onClick?: () => void
    /** Tooltip shown on the drill-down affordance when `onClick` is set. */
    onClickTooltip?: string
    /** Optional content rendered at the bottom of the card, e.g. a deep-link to the underlying data. */
    footer?: JSX.Element | null
}

export function AppMetricSummary({
    name,
    timeSeries,
    previousPeriodTimeSeries,
    description,
    color,
    colorIfZero,
    loading,
    hideIfZero = false,
    onClick,
    onClickTooltip,
    footer,
}: AppMetricSummaryProps): JSX.Element | null {
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

    const diffForDisplay = formatPercentageDiff(total, totalPreviousPeriod)

    const chartColor = total === 0 ? colorIfZero : color
    const seriesOverrides = useMemo(
        () =>
            timeSeries && chartColor
                ? Object.fromEntries(
                      timeSeries.series.map((x): [string, AppMetricsSeriesOverride] => [x.name, { color: chartColor }])
                  )
                : undefined,
        [timeSeries, chartColor]
    )

    // Hide component if hideIfZero is true and there's no data
    if (hideIfZero && !loading && total === 0 && totalPreviousPeriod === 0) {
        return null
    }

    return (
        <div
            className={
                onClick
                    ? 'flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem] cursor-pointer transition-colors hover:border-primary'
                    : 'flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]'
            }
            role={onClick ? 'button' : undefined}
            tabIndex={onClick ? 0 : undefined}
            onClick={onClick}
            onKeyDown={
                onClick
                    ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              onClick()
                          }
                      }
                    : undefined
            }
        >
            <div className="flex flex-row justify-between items-start">
                <LemonLabel info={description}>{name}</LemonLabel>
                {loading ? (
                    <LemonSkeleton className="w-20 h-6 mb-2" />
                ) : (
                    <div className="flex items-center gap-1 text-right text-2xl text-muted-foreground">
                        {onClick ? (
                            <Tooltip title={onClickTooltip ?? 'View matching invocations'}>
                                <IconArrowRight className="text-base text-muted" />
                            </Tooltip>
                        ) : null}
                        {humanFriendlyNumber(total)}
                    </div>
                )}
            </div>
            <div className="flex flex-row justify-end items-center gap-2 text-xs text-muted">
                {loading ? <LemonSkeleton className="w-10 h-4" /> : <>{diffForDisplay}</>}
            </div>

            <div className="flex-1 mt-2">
                <div className="h-[10rem]">
                    {loading ? (
                        <SpinnerOverlay />
                    ) : !timeSeries ? (
                        <div className="flex-1 flex items-center justify-center">
                            <LemonLabel>No data</LemonLabel>
                        </div>
                    ) : (
                        <AppMetricsTimeSeriesChart timeSeries={timeSeries} seriesOverrides={seriesOverrides} minimal />
                    )}
                </div>
            </div>
            {footer ? <div className="mt-2 text-xs text-center">{footer}</div> : null}
        </div>
    )
}
