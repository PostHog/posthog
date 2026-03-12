import { clsx } from 'clsx'

import { AddMetricButton } from 'scenes/experiments/Metrics/AddMetricButton'
import type { MetricContext } from 'scenes/experiments/Metrics/experimentMetricModalLogic'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { MetricCard } from './MetricCard'

export type MetricListProps = {
    metrics: ExperimentMetric[]
    metricContext: MetricContext
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void
    filterTestAccounts: boolean
    className?: string
}

export const MetricList = ({
    metrics,
    metricContext,
    onDelete,
    filterTestAccounts,
    className,
}: MetricListProps): JSX.Element => {
    return (
        <div className={clsx('space-y-3', className)}>
            <span className="font-medium text-default">
                {metricContext.type.charAt(0).toUpperCase() + metricContext.type.slice(1)} metrics
            </span>
            {metrics.map((metric) => (
                <MetricCard
                    key={metric.uuid}
                    metric={metric}
                    metricContext={metricContext}
                    onDelete={onDelete}
                    filterTestAccounts={filterTestAccounts}
                />
            ))}
            <div>
                <AddMetricButton metricContext={metricContext} />
            </div>
        </div>
    )
}
