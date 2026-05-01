import { IconTrending } from '@posthog/icons'
import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { formatPercentage, humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import { UsageMetric } from '~/queries/schema/schema-general'

export type TrendInfo = {
    icon: React.ComponentType<{ className?: string }>
    colorClass: string
    tooltip: string | null
}

export const getTrendFromPercentageChange = (changeFromPreviousPct: number | null): TrendInfo | undefined => {
    if (changeFromPreviousPct === null) {
        return undefined
    }
    if (changeFromPreviousPct === 0) {
        return {
            icon: IconTrendingFlat,
            colorClass: 'text-muted',
            tooltip: 'unchanged',
        }
    }
    if (changeFromPreviousPct > 0) {
        return {
            icon: IconTrending,
            colorClass: 'text-success',
            tooltip: `increased by ${formatPercentage(Math.abs(changeFromPreviousPct))}`,
        }
    }
    return {
        icon: IconTrendingDown,
        colorClass: 'text-danger',
        tooltip: `decreased by ${formatPercentage(Math.abs(changeFromPreviousPct))}`,
    }
}

export const getMetricTooltip = (metric: UsageMetric, trend: TrendInfo | undefined): string => {
    if (trend?.tooltip) {
        return `${metric.name}: ${trend.tooltip}, to ${humanFriendlyNumber(metric.value)} from ${humanFriendlyNumber(metric.previous)}`
    }
    return `${metric.name}: ${humanFriendlyNumber(metric.value)}`
}

const formatValue = (metric: UsageMetric): string => {
    if (metric.format === 'currency') {
        return humanFriendlyCurrency(metric.value)
    }
    return humanFriendlyLargeNumber(metric.value)
}

const DeltaIndicator = ({ pct }: { pct: number | null }): JSX.Element | null => {
    const trend = getTrendFromPercentageChange(pct)
    if (pct === null || !trend) {
        return null
    }
    return (
        <span className={`inline-flex items-center gap-1 text-xs font-semibold tabular-nums ${trend.colorClass}`}>
            <trend.icon className="w-3.5 h-3.5" />
            {formatPercentage(pct)}
        </span>
    )
}

export const UsageMetricCard = ({ metric }: { metric: UsageMetric }): JSX.Element => {
    const trend = getTrendFromPercentageChange(metric.change_from_previous_pct)
    const tooltip = getMetricTooltip(metric, trend)

    return (
        <Tooltip title={tooltip}>
            <div>
                <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-2 max-w-80 h-40">
                    <div className="text-sm font-semibold text-primary truncate">{metric.name}</div>
                    <div className="text-3xl font-bold text-primary tabular-nums tracking-tight leading-none truncate">
                        {formatValue(metric)}
                    </div>
                    {metric.display === 'sparkline' && metric.timeseries && (
                        <div className="h-10 min-h-0">
                            <Sparkline
                                data={metric.timeseries}
                                labels={metric.timeseries_labels}
                                type="bar"
                                maximumIndicator={false}
                                color="muted"
                                className="w-full h-full"
                                withXScale={(x) => ({ ...x, display: false })}
                                withYScale={(y) => ({ ...y, display: false })}
                            />
                        </div>
                    )}
                    <div className="flex items-center justify-between mt-auto">
                        <DeltaIndicator pct={metric.change_from_previous_pct} />
                        <span className="text-xs text-muted whitespace-nowrap ml-auto">
                            Last {metric.interval} days
                        </span>
                    </div>
                </LemonCard>
            </div>
        </Tooltip>
    )
}

export const UsageMetricCardSkeleton = (): JSX.Element => (
    <div className="@container">
        <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
            {[1, 2, 3].map((i) => (
                <LemonCard key={i} className="p-4 h-40">
                    <LemonSkeleton className="h-4 bg-border rounded w-24 mb-2" />
                    <LemonSkeleton className="h-8 bg-border rounded w-32 my-2" />
                    <LemonSkeleton className="h-3 bg-border rounded w-20" />
                </LemonCard>
            ))}
        </div>
    </div>
)
