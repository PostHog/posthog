import { StepOrderValue } from '~/types'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'

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
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={filters.funnel_order_type || StepOrderValue.ORDERED}
            onChange={(stepOrder) => stepOrder && setFilters({ funnel_order_type: stepOrder })}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
