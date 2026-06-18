import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import {
    ExperimentMeanMetric,
    ExperimentMetric,
    ExperimentMetricOutlierHandling as ExperimentMetricOutlierHandlingConfig,
    ExperimentRatioMetric,
} from '~/queries/schema/schema-general'

import { isMetricThresholdSet } from './ExperimentMetricThreshold'

const DESCRIPTION = 'Set winsorization lower and upper bounds to cap metric values at the specified percentiles.'

function OutlierHandlingControls({
    value,
    onChange,
    disabled = false,
}: {
    value: ExperimentMetricOutlierHandlingConfig
    onChange: (next: ExperimentMetricOutlierHandlingConfig) => void
    disabled?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonCheckbox
                    label="Lower bound percentile"
                    disabled={disabled}
                    checked={value.lower_bound_percentile !== undefined}
                    onChange={(checked) => onChange({ ...value, lower_bound_percentile: checked ? 0.05 : undefined })}
                />
                <LemonInput
                    value={value.lower_bound_percentile !== undefined ? value.lower_bound_percentile * 100 : 0}
                    onChange={(newValue) =>
                        value.lower_bound_percentile !== undefined &&
                        onChange({ ...value, lower_bound_percentile: (newValue ?? 0) / 100 })
                    }
                    type="number"
                    step={1}
                    suffix={<span className="text-sm">%</span>}
                    size="small"
                    className={`w-20 transition-opacity ${
                        value.lower_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                    }`}
                />
            </div>
            <div className="flex items-center gap-2">
                <LemonCheckbox
                    label="Upper bound percentile"
                    disabled={disabled}
                    checked={value.upper_bound_percentile !== undefined}
                    onChange={(checked) => onChange({ ...value, upper_bound_percentile: checked ? 0.95 : undefined })}
                />
                <LemonInput
                    value={value.upper_bound_percentile !== undefined ? value.upper_bound_percentile * 100 : 0}
                    onChange={(newValue) =>
                        value.upper_bound_percentile !== undefined &&
                        onChange({ ...value, upper_bound_percentile: (newValue ?? 0) / 100 })
                    }
                    type="number"
                    step={1}
                    suffix={<span className="text-sm">%</span>}
                    size="small"
                    className={`w-20 transition-opacity ${
                        value.upper_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                    }`}
                />
                <div
                    className={`text-xs transition-opacity ${
                        value.upper_bound_percentile === undefined ? 'opacity-0 invisible' : 'opacity-100 visible'
                    }`}
                >
                    <Tooltip
                        title="Useful if a large number of participants in the experiment does not have the event resulting in a 0 value."
                        docLink="https://posthog.com/docs/experiments/metrics#outlier-handling"
                    >
                        <span>
                            <LemonCheckbox
                                label="Ignore zeros when calculating upper bound"
                                disabled={disabled}
                                checked={value.ignore_zeros ?? false}
                                onChange={(checked) => onChange({ ...value, ignore_zeros: checked })}
                            />
                        </span>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}

export function ExperimentMetricOutlierHandling({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    /**
     * Winsorization caps continuous outliers, which is meaningless once a threshold
     * collapses the metric into a binary outcome.
     */
    const disabledByThreshold = isMetricThresholdSet(metric)

    return (
        <SceneSection
            title="Outlier handling"
            titleHelper={<>Prevent outliers from skewing results by capping the lower and upper bounds of a metric.</>}
            description={
                <p className="text-muted text-xs -mb-1">
                    {disabledByThreshold ? 'Not available when a threshold is set.' : DESCRIPTION}
                </p>
            }
        >
            <Tooltip
                title={disabledByThreshold ? 'Outlier handling is not available when a threshold is set.' : undefined}
            >
                <div>
                    <OutlierHandlingControls
                        disabled={disabledByThreshold}
                        value={{
                            lower_bound_percentile: metric.lower_bound_percentile,
                            upper_bound_percentile: metric.upper_bound_percentile,
                            ignore_zeros: metric.ignore_zeros,
                        }}
                        onChange={(next) => handleSetMetric({ ...metric, ...next })}
                    />
                </div>
            </Tooltip>
        </SceneSection>
    )
}

// When no bounds are set, drop the whole config so the metric stays clean (and its
// fingerprint unchanged). ignore_zeros only matters alongside an upper bound.
function normalizeOutlierHandling(
    config: ExperimentMetricOutlierHandlingConfig
): ExperimentMetricOutlierHandlingConfig | undefined {
    if (config.lower_bound_percentile === undefined && config.upper_bound_percentile === undefined) {
        return undefined
    }
    return config
}

export function ExperimentRatioMetricOutlierHandling({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentRatioMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    return (
        <SceneSection
            title="Outlier handling"
            titleHelper={
                <>
                    Prevent outliers from skewing results by capping the numerator and denominator independently. There
                    is no per-user ratio to cap, so each component is winsorized on its own.
                </>
            }
            description={<p className="text-muted text-xs -mb-1">{DESCRIPTION}</p>}
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <LemonLabel>Numerator</LemonLabel>
                    <OutlierHandlingControls
                        value={metric.numerator_outlier_handling ?? {}}
                        onChange={(next) =>
                            handleSetMetric({ ...metric, numerator_outlier_handling: normalizeOutlierHandling(next) })
                        }
                    />
                </div>
                <div className="flex flex-col gap-2">
                    <LemonLabel>Denominator</LemonLabel>
                    <OutlierHandlingControls
                        value={metric.denominator_outlier_handling ?? {}}
                        onChange={(next) =>
                            handleSetMetric({ ...metric, denominator_outlier_handling: normalizeOutlierHandling(next) })
                        }
                    />
                </div>
            </div>
        </SceneSection>
    )
}
