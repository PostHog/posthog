import { useMemo } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonLabel, LemonSkeleton, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import { MetricCard, type MetricChange } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export type AppMetricSummaryProps = {
    name: string
    description: string
    color?: string
    colorIfZero?: string
    timeSeries: AppMetricsTimeSeriesResponse | null
    previousPeriodTimeSeries?: AppMetricsTimeSeriesResponse | null
    loading?: boolean
    hideIfZero?: boolean
    /** Which direction of change is good, for the change pill's color. Defaults from the tile
     *  `color`: danger/warning tiles (failures, drops) treat an increase as bad. */
    goodDirection?: 'up' | 'down'
    /** When set, the tile becomes clickable (e.g. to drill into matching invocations). */
    onClick?: () => void
    /** Tooltip shown on the drill-down affordance when `onClick` is set. */
    onClickTooltip?: string
    /** Optional content rendered at the bottom of the card, e.g. a deep-link to the underlying data. */
    footer?: JSX.Element | null
}

function sumSeries(timeSeries: AppMetricsTimeSeriesResponse | null | undefined): number {
    if (!timeSeries) {
        return 0
    }
    return timeSeries.series.reduce((acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0), 0)
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
    goodDirection,
    onClick,
    onClickTooltip,
    footer,
}: AppMetricSummaryProps): JSX.Element | null {
    const theme = useChartTheme()

    const total = useMemo(() => sumSeries(timeSeries), [timeSeries])
    const totalPreviousPeriod = useMemo(() => sumSeries(previousPeriodTimeSeries), [previousPeriodTimeSeries])

    const change = useMemo<MetricChange | null>(() => {
        const percent = ((total - totalPreviousPeriod) / totalPreviousPeriod) * 100
        return Number.isFinite(percent) ? { value: percent } : null
    }, [total, totalPreviousPeriod])

    // Per-bucket sum across series — the tile is a single-line summary even when the
    // underlying response has several series.
    const data = useMemo(
        () =>
            timeSeries
                ? timeSeries.labels.map((_, i) => timeSeries.series.reduce((acc, s) => acc + (s.values[i] ?? 0), 0))
                : [],
        [timeSeries]
    )

    const labels = useMemo(() => {
        if (!timeSeries) {
            return []
        }
        const hasTimePart = timeSeries.labels.some((label) => label.includes(' '))
        return timeSeries.labels.map((label) => dayjs(label).format(hasTimePart ? 'MMM D, HH:mm' : 'MMM D, YYYY'))
    }, [timeSeries])

    const chartColor = total === 0 ? colorIfZero : color
    const resolvedGoodDirection =
        goodDirection ?? (color === getColorVar('danger') || color === getColorVar('warning') ? 'down' : 'up')

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
            {loading ? (
                <>
                    <div className="flex flex-row justify-between items-start">
                        <LemonLabel info={description}>{name}</LemonLabel>
                        <LemonSkeleton className="w-20 h-6 mb-2" />
                    </div>
                    <div className="flex-1 mt-2 h-[10rem]">
                        <SpinnerOverlay />
                    </div>
                </>
            ) : !timeSeries ? (
                <>
                    <LemonLabel info={description}>{name}</LemonLabel>
                    <div className="flex-1 flex items-center justify-center h-[10rem]">
                        <LemonLabel>No data</LemonLabel>
                    </div>
                </>
            ) : (
                <MetricCard
                    title={
                        <span className="flex items-center gap-1">
                            <LemonLabel info={description}>{name}</LemonLabel>
                            {onClick ? (
                                <Tooltip title={onClickTooltip ?? 'View matching invocations'}>
                                    <IconArrowRight className="text-base text-muted" />
                                </Tooltip>
                            ) : null}
                        </span>
                    }
                    value={total}
                    data={data}
                    labels={labels}
                    theme={theme}
                    color={chartColor}
                    sparklineHeight={160}
                    formatValue={humanFriendlyNumber}
                    change={change}
                    goodDirection={resolvedGoodDirection}
                    changeTooltip="Compared to the previous period"
                    // '' suppresses the resting subtitle (a null would fall back to the last
                    // bucket's date, misleading under a period-total headline)
                    restingSubtitle={
                        previousPeriodTimeSeries ? `vs. ${humanFriendlyNumber(totalPreviousPeriod)} prior` : ''
                    }
                />
            )}
            {footer ? <div className="mt-2 text-xs text-center">{footer}</div> : null}
        </div>
    )
}
