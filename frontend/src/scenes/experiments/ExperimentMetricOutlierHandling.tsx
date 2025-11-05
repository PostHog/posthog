import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExperimentMeanMetric, ExperimentMetric } from '~/queries/schema/schema-general'

export function ExperimentMetricOutlierHandling({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    return (
        <SceneSection
            title="Outlier handling"
            titleHelper={<>Prevent outliers from skewing results by capping the lower and upper bounds of a metric.</>}
            description={
                <>Set winsorization lower and upper bounds to cap metric values at the specified percentiles.</>
            }
        >
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <LemonCheckbox
                        label="Lower bound percentile"
                        checked={metric.lower_bound_percentile !== undefined}
                        onChange={(checked) =>
                            handleSetMetric({ ...metric, lower_bound_percentile: checked ? 0.05 : undefined })
                        }
                    />
                    <LemonInput
                        value={metric.lower_bound_percentile !== undefined ? metric.lower_bound_percentile * 100 : 0}
                        onChange={(value) =>
                            metric.lower_bound_percentile !== undefined &&
                            handleSetMetric({ ...metric, lower_bound_percentile: (value ?? 0) / 100 })
                        }
                        type="number"
                        step={1}
                        suffix={<span className="text-sm">%</span>}
                        size="small"
                        className={`w-20 transition-opacity ${
                            metric.lower_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                        }`}
                    />
                </div>
                <div className="flex items-center gap-2">
                    <LemonCheckbox
                        label="Upper bound percentile"
                        checked={metric.upper_bound_percentile !== undefined}
                        onChange={(checked) =>
                            handleSetMetric({ ...metric, upper_bound_percentile: checked ? 0.95 : undefined })
                        }
                    />
                    <LemonInput
                        value={metric.upper_bound_percentile !== undefined ? metric.upper_bound_percentile * 100 : 0}
                        onChange={(value) =>
                            metric.upper_bound_percentile !== undefined &&
                            handleSetMetric({ ...metric, upper_bound_percentile: (value ?? 0) / 100 })
                        }
                        type="number"
                        step={1}
                        suffix={<span className="text-sm">%</span>}
                        size="small"
                        className={`w-20 transition-opacity ${
                            metric.upper_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                        }`}
                    />
                    <div
                        className={`text-xs transition-opacity ${
                            metric.upper_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                        }`}
                    >
                        <Tooltip
                            title="Useful if a large number of participants in the experiment does not have the event resulting in a 0 value."
                            docLink="https://posthog.com/docs/experiments/metrics#outlier-handling"
                        >
                            <span>
                                <LemonCheckbox
                                    label="Ignore zeros when calculating upper bound"
                                    checked={metric.ignore_zeros ?? false}
                                    onChange={(checked) => handleSetMetric({ ...metric, ignore_zeros: checked })}
                                />
                            </span>
                        </Tooltip>
                    </div>
                </div>
            </div>
        </SceneSection>
    )
}
