import { IconTrending } from '@posthog/icons'
import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { formatPercentage, humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import { UsageMetric } from '~/queries/schema/schema-general'

export const UsageMetricCard = ({ metric }: { metric: UsageMetric }): JSX.Element => {
    const formatValue = (): string => {
        if (metric.format === 'currency') {
            return humanFriendlyCurrency(metric.value)
        }
        return humanFriendlyLargeNumber(metric.value)
    }
    let trend
    if (metric.change_from_previous_pct === null) {
        trend = undefined
    } else if (metric.change_from_previous_pct === 0) {
        trend = {
            icon: IconTrendingFlat,
            color: getColorVar('muted'),
            tooltip: null,
        }
    } else if (metric.change_from_previous_pct > 0) {
        trend = {
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: `increased by ${formatPercentage(Math.abs(metric.change_from_previous_pct))}`,
        }
    } else if (metric.change_from_previous_pct < 0) {
        trend = {
            icon: IconTrendingDown,
            color: getColorVar('danger'),
            tooltip: `decreased by ${formatPercentage(Math.abs(metric.change_from_previous_pct))}`,
        }
    }

    const tooltip =
        trend && trend.tooltip
            ? `${metric.name}: ${trend.tooltip}, to ${humanFriendlyNumber(metric.value)} from ${humanFriendlyNumber(metric.previous)}`
            : `${metric.name}: ${humanFriendlyNumber(metric.value)}`

    return (
        <Tooltip title={tooltip}>
            <div>
                <LemonCard hoverEffect={false} className="p-4 flex flex-col flex-1 justify-between max-w-80 min-h-36 ">
                    <div>
                        <div className="text-sm font-semibold text-muted-alt mb-1">{metric.name}</div>
                        <div className="text-3xl font-bold text-primary my-2 truncate">{formatValue()}</div>
                    </div>
                    {trend && metric?.change_from_previous_pct && (
                        <div style={{ color: trend.color }}>
                            <trend.icon color={trend.color} />
                            {formatPercentage(metric.change_from_previous_pct)}
                        </div>
                    )}
                    <div className="text-xs text-muted">Last {metric.interval} days</div>
                </LemonCard>
            </div>
        </Tooltip>
    )
}

export const UsageMetricCardSkeleton = (): JSX.Element => (
    <div className="@container">
        <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
            {[1, 2, 3].map((i) => (
                <LemonCard key={i} className="p-4 min-h-36">
                    <LemonSkeleton className="h-4 bg-border rounded w-24 mb-2" />
                    <LemonSkeleton className="h-8 bg-border rounded w-32 my-2" />
                    <LemonSkeleton className="h-3 bg-border rounded w-20" />
                </LemonCard>
            ))}
        </div>
    </div>
)
