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
    const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
        !breakdownAttributionType
            ? BreakdownAttributionType.FirstTouch
            : breakdownAttributionType === BreakdownAttributionType.Step
              ? `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
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
                            hidden: stepIndex >= stepCount,
                        })),
                    hidden: funnel_order_type === StepOrderValue.UNORDERED,
                },
            ]}
            onChange={(value) => {
                if (!value) {
                    return
                }
                const [attributionType, attributionValue] = value.split('/')
                onChange(
                    attributionType as BreakdownAttributionType,
                    attributionValue ? parseInt(attributionValue) : undefined
                )
            }}
            dropdownMaxContentWidth
            data-attr="experiment-breakdown-attribution"
        />
    )
}
