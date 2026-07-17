import { LemonInput } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import {
    ExperimentMeanMetric,
    ExperimentMetric,
    MathType,
    isExperimentMeanMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

/**
 * Threshold turns a per-user accumulated value into a binary outcome ("did this user reach N"),
 * so it only makes sense for math types that sum/count per user.
 */
const THRESHOLD_ENABLED_MATH_TYPES = new Set<MathType>([
    ExperimentMetricMathType.Sum,
    ExperimentMetricMathType.TotalCount,
])

export function isThresholdAvailableForMath(math: MathType | undefined): boolean {
    return math !== undefined && THRESHOLD_ENABLED_MATH_TYPES.has(math)
}

/** Whether the metric has a valid threshold applied, so the header should show a cue.
 *  A 0 threshold is treated as unset (an always-true proportion is meaningless). */
export const isMetricThresholdSet = (metric: ExperimentMetric): boolean =>
    isExperimentMeanMetric(metric) && !!metric.threshold

export const isMetricThresholdCueVisible = (metric: ExperimentMetric): metric is ExperimentMeanMetric =>
    isExperimentMeanMetric(metric) && !!metric.threshold && isThresholdAvailableForMath(metric.source.math)

export interface ExperimentMetricThresholdProps {
    math: MathType | undefined
    value: number | undefined
    onChange: (value: number | undefined) => void
}

export function ExperimentMetricThreshold({ math, value, onChange }: ExperimentMetricThresholdProps): JSX.Element {
    const enabled = isThresholdAvailableForMath(math)

    return (
        <div className="mt-4">
            <LemonLabel
                info="Reports the percentage of exposed users whose per-user value reaches or exceeds this threshold. Only available for summed or counted metrics."
                className="mb-1"
            >
                Threshold
            </LemonLabel>
            <Tooltip title={enabled ? undefined : 'Thresholds are only available for summed or counted metrics'}>
                <LemonInput
                    type="number"
                    className="max-w-32"
                    fullWidth={false}
                    min={0}
                    step={1}
                    placeholder="e.g. 100"
                    value={value}
                    /**
                     * Treat empty / cleared (0) / NaN as "no threshold" so dependent fields re-enable.
                     */
                    onChange={(newValue) => onChange(newValue ? newValue : undefined)}
                    disabled={!enabled}
                />
            </Tooltip>
            <div className="text-muted text-xs mt-1">
                {enabled
                    ? 'For example, reports the percentage of users who reach 100 total words across the experiment.'
                    : 'Thresholds are only available for summed or counted metrics.'}
            </div>
        </div>
    )
}
