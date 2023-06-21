import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { StepOrderValue } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { FunnelsFilter } from '~/queries/schema'

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

    const { funnel_order_type } = (insightFilter || {}) as FunnelsFilter

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnel_order_type || StepOrderValue.ORDERED}
            onChange={(stepOrder) => stepOrder && updateInsightFilter({ funnel_order_type: stepOrder })}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
