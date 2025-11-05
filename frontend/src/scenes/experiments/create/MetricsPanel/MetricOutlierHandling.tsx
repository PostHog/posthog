import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentMeanMetric } from '~/queries/schema/schema-general'

/**
 * Only for mean metrics
 */
export type MetricOutlierHandlingProps = {
    metric: ExperimentMetric
}

export const MetricOutlierHandling = ({ metric }: MetricOutlierHandlingProps): JSX.Element | null => {
    if (!isExperimentMeanMetric(metric)) {
        return null
    }

    const hasLower = metric.lower_bound_percentile != null
    const hasUpper = metric.upper_bound_percentile != null

    return (
        <div className="text-xs">
            <span className="text-muted">Outlier handling:</span>{' '}
            <span className="font-semibold">
                {hasLower && `Lower ${metric.lower_bound_percentile}%`}
                {hasLower && hasUpper && ', '}
                {hasUpper && `Upper ${metric.upper_bound_percentile}%`}
            </span>
        </div>
    )
}
