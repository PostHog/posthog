import { useMemo } from 'react'

import { IconArrowRight, IconInfo } from '@posthog/icons'
import { Card, CardContent, Skeleton, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'
import {
    Metric,
    type MetricChange,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

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

function TitleWithInfo({ name, description }: { name: string; description: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1">
            {name}
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex cursor-default" />}>
                    <IconInfo className="text-sm opacity-60" />
                </TooltipTrigger>
                <TooltipContent className="max-w-60">{description}</TooltipContent>
            </Tooltip>
        </span>
    )
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
    const hasSparkline = !loading && data.length > 0

    // Hide component if hideIfZero is true and there's no data
    if (hideIfZero && !loading && total === 0 && totalPreviousPeriod === 0) {
        return null
    }

    return (
        <Card
            size="sm"
            flush={hasSparkline}
            className={cn(
                'flex-1 min-w-[16rem]',
                onClick && 'cursor-pointer transition-transform hover:-translate-y-0.5'
            )}
            role={onClick ? 'button' : undefined}
            tabIndex={onClick ? 0 : undefined}
            onClick={onClick}
            onKeyDown={
                onClick
                    ? (e: React.KeyboardEvent) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              onClick()
                          }
                      }
                    : undefined
            }
        >
            {loading ? (
                <CardContent className="flex flex-col gap-2">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-7 w-20" />
                </CardContent>
            ) : !timeSeries ? (
                <CardContent className="flex flex-col gap-2">
                    <TitleWithInfo name={name} description={description} />
                    <div className="text-sm opacity-60">No data</div>
                </CardContent>
            ) : (
                <Metric
                    className="px-3 text-primary"
                    value={total}
                    data={hasSparkline ? data : undefined}
                    labels={hasSparkline ? labels : undefined}
                    theme={theme}
                    color={chartColor}
                    goodDirection={resolvedGoodDirection}
                    formatValue={humanFriendlyNumber}
                    change={change}
                    changeTooltip="Compared to the previous period"
                    // '' suppresses the resting subtitle (a null would fall back to the last
                    // bucket's date, misleading under a period-total headline)
                    restingSubtitle={
                        previousPeriodTimeSeries ? `vs. ${humanFriendlyNumber(totalPreviousPeriod)} prior` : ''
                    }
                    sparklineHeight={60}
                >
                    <MetricHeader>
                        <MetricTitle>
                            <span className="inline-flex items-center gap-1">
                                <TitleWithInfo name={name} description={description} />
                                {onClick ? (
                                    <Tooltip>
                                        <TooltipTrigger render={<span className="inline-flex" />}>
                                            <IconArrowRight className="text-sm opacity-60" />
                                        </TooltipTrigger>
                                        <TooltipContent>{onClickTooltip ?? 'View matching invocations'}</TooltipContent>
                                    </Tooltip>
                                ) : null}
                            </span>
                        </MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline className="mt-3 -mx-3" />
                </Metric>
            )}
            {footer ? (
                <div className={cn('mt-2 text-xs text-center', hasSparkline && 'px-3 pb-3')}>{footer}</div>
            ) : null}
        </Card>
    )
}
