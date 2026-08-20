import { LemonSelect } from '@posthog/lemon-ui'

import { FUNNEL_STEP_COUNT_LIMIT } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'

import { ExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

export function MetricBreakdownAttribution({
    metric,
    onChange,
}: {
    metric: ExperimentFunnelMetric
    onChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
}): JSX.Element {
    const { breakdownAttributionType, breakdownAttributionValue, funnel_order_type } = metric
    const stepCount = metric.series?.length || 0

    /**
     * We need to construct the current value shown based on the attribution type and the funnel order.
     * we default to `first touch`, but if the funnel is unordered, insterad of the step choice
     * we show the "any step" option.
     * For the step attribution type, we need to show the value.
     */
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
                            /**
                             * if the funnel was shortened, an our of range stale selection gets hidden.
                             * this guard keeps it visible
                             */
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
                /**
                 * the backend requires a breakdown attribution value for step attribution,
                 * so "Any step" stores zero.
                 */
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
