import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import {
    ExperimentMeanMetric,
    ExperimentMetric,
    MathType,
    isExperimentMeanMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

// The decomposition (per-value sums add back to the total) only holds for additive metrics, so the
// split is offered for the same math types as the threshold: summed and counted values.
const VALUE_BREAKDOWN_ENABLED_MATH_TYPES = new Set<MathType>([
    ExperimentMetricMathType.Sum,
    ExperimentMetricMathType.TotalCount,
])

export function isValueBreakdownAvailableForMath(math: MathType | undefined): boolean {
    return math !== undefined && VALUE_BREAKDOWN_ENABLED_MATH_TYPES.has(math)
}

export const isMetricValueBreakdownSet = (metric: ExperimentMetric): boolean =>
    isExperimentMeanMetric(metric) && !!metric.value_breakdown_property

export function ExperimentMetricValueBreakdown({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const enabled = isValueBreakdownAvailableForMath(metric.source.math)

    return (
        <SceneSection
            title="Split by property value"
            titleHelper={
                <>
                    Decompose this metric across the values of a property read off the metric event. Unlike a breakdown,
                    every split keeps the full exposure denominator, so the per-value means add up to the overall mean.
                </>
            }
            description={<p className="text-muted text-xs -mb-1">Only available for counted or summed metrics.</p>}
        >
            <TaxonomicStringPopover
                groupType={TaxonomicFilterGroupType.EventProperties}
                groupTypes={[TaxonomicFilterGroupType.EventProperties]}
                value={metric.value_breakdown_property ?? null}
                onChange={(value) =>
                    handleSetMetric({
                        ...metric,
                        // The clear (X) affordance reports an empty string; treat that as "no split".
                        value_breakdown_property: value || undefined,
                        // The decomposition needs the un-split denominator and raw per-user values, so it is
                        // mutually exclusive with a breakdown, winsorization, and thresholds. Clearing them on
                        // set keeps the metric valid (the backend rejects these combinations).
                        ...(value
                            ? {
                                  breakdownFilter: undefined,
                                  threshold: undefined,
                                  lower_bound_percentile: undefined,
                                  upper_bound_percentile: undefined,
                                  ignore_zeros: undefined,
                              }
                            : {}),
                    })
                }
                placeholder="Select a property"
                allowClear
                size="small"
                disabledReason={enabled ? undefined : 'Only available for counted or summed metrics'}
            />
        </SceneSection>
    )
}
