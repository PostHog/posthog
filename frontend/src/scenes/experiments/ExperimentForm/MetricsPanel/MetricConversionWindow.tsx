import { formatUnitByQuantity } from 'scenes/experiments/utils'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit } from '~/types'

export type MetricConversionWindowProps = {
    metric: ExperimentMetric
}

export const MetricConversionWindow = ({ metric }: MetricConversionWindowProps): JSX.Element => {
    if (metric.conversion_window != null && metric.conversion_window_unit) {
        const unit = metric.conversion_window_unit || FunnelConversionWindowTimeUnit.Day
        return (
            <div className="text-xs">
                <span className="text-muted">Conversion window:</span>{' '}
                <span className="font-semibold">
                    {metric.conversion_window} {formatUnitByQuantity(metric.conversion_window, unit)}
                </span>
            </div>
        )
    }
    return (
        <div className="text-xs">
            <span className="text-muted">Conversion window:</span>{' '}
            <span className="font-semibold">Experiment duration</span>
        </div>
    )
}
