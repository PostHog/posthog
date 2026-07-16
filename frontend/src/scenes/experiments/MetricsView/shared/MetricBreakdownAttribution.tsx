import { LemonSelect } from '@posthog/lemon-ui'

import { ExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function MetricBreakdownAttribution({
    metric,
    onChange,
}: {
    metric: ExperimentFunnelMetric
    onChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
}): JSX.Element {
    const { breakdownAttributionType, breakdownAttributionValue, funnel_order_type } = metric
    const stepCount = metric.series?.length || 0

    // Encode the "Specific step" selection as `step/<index>` so a single LemonSelect can
    // represent both the attribution type and (for step attribution) the step index.
    // Unordered funnels expose step attribution as "Any step" (bare `step`, index ignored).
    const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
        !breakdownAttributionType
            ? BreakdownAttributionType.FirstTouch
            : breakdownAttributionType === BreakdownAttributionType.Step
              ? funnel_order_type === StepOrderValue.UNORDERED
                  ? BreakdownAttributionType.Step
                  : `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
              : breakdownAttributionType

    return (
        <LemonSelect
            size="small"
            value={currentValue}
            placeholder="Attribution"
            options={[
                { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                {
                    value: BreakdownAttributionType.Step,
                    label: 'Any step',
                    hidden: funnel_order_type !== StepOrderValue.UNORDERED,
                },
                {
                    label: 'Specific step',
                    options: Array(FUNNEL_STEP_COUNT_LIMIT)
                        .fill(null)
                        .map((_, stepIndex) => ({
                            value: `${BreakdownAttributionType.Step}/${stepIndex}`,
                            label: `Step ${stepIndex + 1}`,
                            // Keep a stored out-of-range step visible (e.g. after the funnel was
                            // shortened) so the stale selection can be seen and corrected.
                            hidden: stepIndex >= stepCount && stepIndex !== breakdownAttributionValue,
                        })),
                    hidden: funnel_order_type === StepOrderValue.UNORDERED,
                },
            ]}
            onChange={(value) => {
                if (!value) {
                    return
                }
                const [attributionType, attributionValue] = value.split('/')
                // Step attribution always stores an index ("Any step" stores 0, matching
                // insights' AttributionFilter); the backend rejects step attribution without one.
                onChange(
                    attributionType as BreakdownAttributionType,
                    attributionType === BreakdownAttributionType.Step ? parseInt(attributionValue) || 0 : undefined
                )
            }}
            dropdownMaxContentWidth
            data-attr="experiment-breakdown-attribution"
        />
    )
}
