import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import { UsageMetric } from '~/queries/schema/schema-general'

export const UsageMetricCard = ({ metric }: { metric: UsageMetric }): JSX.Element => {
    const formatValue = (): string => {
        if (metric.format === 'currency') {
            return humanFriendlyCurrency(metric.value)
        }
        return humanFriendlyLargeNumber(metric.value)
    }

    return (
        <LemonCard hoverEffect={false} className="p-4 flex-1 max-w-[300px]">
            <div className="text-sm font-semibold text-muted-alt mb-1">{metric.name}</div>
            <Tooltip title={humanFriendlyNumber(metric.value)}>
                <div className="text-3xl font-bold text-primary my-2 truncate">{formatValue()}</div>
            </Tooltip>
            <div className="text-xs text-muted">Last {metric.interval} days</div>
        </LemonCard>
    )
}

export const UsageMetricCardSkeleton = (): JSX.Element => (
    <div className="@container">
        <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
            {[1, 2, 3].map((i) => (
                <LemonCard key={i} className="p-4">
                    <LemonSkeleton className="h-4 bg-border rounded w-24 mb-2" />
                    <LemonSkeleton className="h-8 bg-border rounded w-32 my-2" />
                    <LemonSkeleton className="h-3 bg-border rounded w-20" />
                </LemonCard>
            ))}
        </div>
    </div>
)
