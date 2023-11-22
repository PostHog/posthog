import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema'
import { BreakdownAttributionType, EditorFilterProps, StepOrderValue } from '~/types'

import { FUNNEL_STEP_COUNT_LIMIT } from './FunnelsQuerySteps'

export function Attribution({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, steps } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { breakdown_attribution_type, breakdown_attribution_value, funnel_order_type } = (insightFilter ||
        {}) as FunnelsFilter

    const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
        !breakdown_attribution_type
            ? BreakdownAttributionType.FirstTouch
            : breakdown_attribution_type === BreakdownAttributionType.Step
            ? `${breakdown_attribution_type}/${breakdown_attribution_value || 0}`
            : breakdown_attribution_type

    return (
        <LemonSelect
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
                            hidden: stepIndex >= steps.length,
                        })),
                    hidden: funnel_order_type === StepOrderValue.UNORDERED,
                },
            ]}
            onChange={(value) => {
                const [breakdownAttributionType, breakdownAttributionValue] = (value || '').split('/')
                if (value) {
                    updateInsightFilter({
                        breakdown_attribution_type: breakdownAttributionType as BreakdownAttributionType,
                        breakdown_attribution_value: breakdownAttributionValue
                            ? parseInt(breakdownAttributionValue)
                            : 0,
                    })
                }
            }}
            dropdownMaxContentWidth={true}
            data-attr="breakdown-attributions"
        />
    )
}
