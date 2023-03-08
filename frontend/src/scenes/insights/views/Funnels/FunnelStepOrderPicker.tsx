import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilterType, StepOrderValue } from '~/types'
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

export function FunnelStepOrderPickerDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return <FunnelStepOrderPickerComponent setFilters={updateInsightFilter} {...insightFilter} />
}

export function FunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return <FunnelStepOrderPickerComponent setFilters={setFilters} {...filters} />
}

type FunnelStepOrderPickerComponentProps = {
    setFilters: (filters: Partial<FunnelsFilterType>) => void
} & FunnelsFilterType

export function FunnelStepOrderPickerComponent({
    funnel_order_type,
    setFilters,
}: FunnelStepOrderPickerComponentProps): JSX.Element {
    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnel_order_type || StepOrderValue.ORDERED}
            onChange={(stepOrder) => stepOrder && setFilters({ funnel_order_type: stepOrder })}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
