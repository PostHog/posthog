import { LemonCheckbox } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExperimentMeanMetric, ExperimentMetric } from '~/queries/schema/schema-general'

export function ExperimentMetricOutlierHandling({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <SceneSection
            title="Outlier handling"
            titleHelper={<>Prevent outliers from skewing results by capping the lower and upper bounds of a metric.</>}
            hideTitleAndDescription={!newSceneLayout}
            description={
                <>Set winsorization lower and upper bounds to cap metric values at the specified percentiles.</>
            }
        >
            {!newSceneLayout && (
                <>
                    <LemonLabel
                        className="mb-1"
                        info="Prevent outliers from skewing results by capping the lower and upper bounds of a metric."
                    />
                    <p className="text-sm text-muted-alt">
                        Set winsorization lower and upper bounds to cap metric values at the specified percentiles.
                    </p>
                </>
            )}

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
                </div>
            </div>
        </SceneSection>
    )
}
