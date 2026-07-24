import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

interface StepOption {
    key?: string
    label: string
    value: StepOrderValue
}

const options: StepOption[] = [
    {
        label: 'Sequential',
        value: StepOrderValue.ORDERED,
    },
    {
        label: 'Strict order',
        value: StepOrderValue.STRICT,
    },
    {
        label: 'Any order',
        value: StepOrderValue.UNORDERED,
    },
]

export function FunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelOrderType, breakdownAttributionType, breakdownAttributionValue } = (insightFilter ||
        {}) as FunnelsFilter

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnelOrderType || StepOrderValue.ORDERED}
            onChange={(stepOrder) => {
                if (!stepOrder) {
                    return
                }
                const update: Partial<FunnelsFilter> = { funnelOrderType: stepOrder }
                // Unordered funnels only allow the first step for breakdown attribution, so reset a
                // stale "Specific step" selection to the first step — otherwise the invalid combo
                // reaches the backend and fails the insight with a "Try again" loop.
                if (
                    stepOrder === StepOrderValue.UNORDERED &&
                    breakdownAttributionType === BreakdownAttributionType.Step &&
                    breakdownAttributionValue !== 0
                ) {
                    update.breakdownAttributionValue = 0
                }
                updateInsightFilter(update)
            }}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
