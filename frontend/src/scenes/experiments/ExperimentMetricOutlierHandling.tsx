import { LemonCheckbox } from '@posthog/lemon-ui'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ExperimentMeanMetric, ExperimentMetric } from '~/queries/schema/schema-general'

export function ExperimentMetricOutlierHandling({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    return (
        <div>
            <LemonLabel>Outlier handling</LemonLabel>
            <div className="flex items-center gap-2">
                <LemonCheckbox
                    label="Lower bound"
                    checked={metric.lower_bound_percentile !== undefined}
                    onChange={(checked) =>
                        handleSetMetric({ ...metric, lower_bound_percentile: checked ? 0.1 : undefined })
                    }
                />
                {metric.lower_bound_percentile !== undefined && (
                    <LemonInput
                        value={metric.lower_bound_percentile * 100}
                        onChange={(value) => handleSetMetric({ ...metric, lower_bound_percentile: (value ?? 0) / 100 })}
                        type="number"
                        step={1}
                        suffix={<span className="text-sm">%</span>}
                    />
                )}
            </div>
            <div className="flex items-center gap-2">
                <LemonCheckbox
                    label="Upper bound"
                    checked={metric.upper_bound_percentile !== undefined}
                    onChange={(checked) =>
                        handleSetMetric({ ...metric, upper_bound_percentile: checked ? 0.9 : undefined })
                    }
                />
                {metric.upper_bound_percentile !== undefined && (
                    <LemonInput
                        value={metric.upper_bound_percentile * 100}
                        onChange={(value) => handleSetMetric({ ...metric, upper_bound_percentile: (value ?? 0) / 100 })}
                        type="number"
                        step={1}
                        suffix={<span className="text-sm">%</span>}
                    />
                )}
            </div>
        </div>
    )
}
