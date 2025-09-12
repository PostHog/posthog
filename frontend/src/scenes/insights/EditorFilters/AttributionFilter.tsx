import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, EditorFilterProps, StepOrderValue } from '~/types'

import { FUNNEL_STEP_COUNT_LIMIT } from './FunnelsQuerySteps'

export function Attribution({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, steps } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { breakdownAttributionType, breakdownAttributionValue, funnelOrderType } = (insightFilter ||
        {}) as FunnelsFilter

    const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
        !breakdownAttributionType
            ? BreakdownAttributionType.FirstTouch
            : breakdownAttributionType === BreakdownAttributionType.Step
              ? `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
              : breakdownAttributionType

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
                    hidden: funnelOrderType !== StepOrderValue.UNORDERED,
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
                    hidden: funnelOrderType === StepOrderValue.UNORDERED,
                },
            ]}
            onChange={(value) => {
                const [breakdownAttributionType, breakdownAttributionValue] = (value || '').split('/')
                if (value) {
                    updateInsightFilter({
                        breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                        breakdownAttributionValue: breakdownAttributionValue ? parseInt(breakdownAttributionValue) : 0,
                    })
                }
            }}
            dropdownMaxContentWidth={true}
            data-attr="breakdown-attributions"
        />
    )
}
