import { LemonSelect } from '@posthog/lemon-ui'

import { ExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

import { FUNNEL_STEP_COUNT_LIMIT } from 'products/product_analytics/frontend/insights/funnels/editor/FunnelsQuerySteps'

export type BreakdownAttributionValue = BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}`

/**
 * We need to construct the current value shown based on the attribution type and the funnel order.
 * we default to `first touch`, but if the funnel is unordered, insterad of the step choice
 * we show the "any step" option.
 * For the step attribution type, we need to show the value.
 */
export function breakdownAttributionValue(metric: ExperimentFunnelMetric): BreakdownAttributionValue {
    const { breakdownAttributionType, breakdownAttributionValue, funnel_order_type } = metric
    return !breakdownAttributionType
        ? BreakdownAttributionType.FirstTouch
        : breakdownAttributionType === BreakdownAttributionType.Step
          ? funnel_order_type === StepOrderValue.UNORDERED
              ? BreakdownAttributionType.Step
              : `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
          : breakdownAttributionType
}

export function parseBreakdownAttribution(value: string): [BreakdownAttributionType, number | undefined] {
    const [attributionType, attributionValue] = value.split('/')
    /**
     * the backend requires a breakdown attribution value for step attribution,
     * so "Any step" stores zero.
     */
    return [
        attributionType as BreakdownAttributionType,
        attributionType === BreakdownAttributionType.Step ? parseInt(attributionValue) || 0 : undefined,
    ]
}

export function BreakdownAttributionHelp({ unordered }: { unordered: boolean }): JSX.Element {
    return (
        <>
            Which funnel step the breakdown value is read from for each user:
            <ul className="list-disc pl-4">
                <li>
                    <strong>First touchpoint</strong>: the first property value seen in any step
                </li>
                <li>
                    <strong>Last touchpoint</strong>: the last property value seen across all steps
                </li>
                <li>
                    <strong>All steps</strong>: The property value must appear on all steps
                </li>
                {unordered ? (
                    <li>
                        <strong>Any step</strong>: value at any matching step
                    </li>
                ) : (
                    <li>
                        <strong>Specific step</strong>: value at a step you choose
                    </li>
                )}
            </ul>
        </>
    )
}

export function MetricBreakdownAttribution({
    metric,
    onChange,
}: {
    metric: ExperimentFunnelMetric
    onChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
}): JSX.Element {
    const { breakdownAttributionValue: attributionStep, funnel_order_type } = metric
    const stepCount = metric.series?.length || 0

    const currentValue = breakdownAttributionValue(metric)

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
                            hidden: stepIndex >= stepCount && stepIndex !== attributionStep,
                        })),
                    hidden: funnel_order_type === StepOrderValue.UNORDERED,
                },
            ]}
            onChange={(value) => {
                if (!value) {
                    return
                }
                onChange(...parseBreakdownAttribution(value))
            }}
            dropdownMaxContentWidth
            data-attr="experiment-breakdown-attribution"
        />
    )
}
