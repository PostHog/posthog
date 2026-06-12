import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { funnelDataLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelDataLogic'
import { FunnelsFilter } from '@posthog/query-frontend/schema/schema-general'

import { insightLogic } from 'scenes/insights/insightLogic'

import { StepOrderValue } from '~/types'

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

    const { funnelOrderType } = (insightFilter || {}) as FunnelsFilter

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnelOrderType || StepOrderValue.ORDERED}
            onChange={(stepOrder) => stepOrder && updateInsightFilter({ funnelOrderType: stepOrder })}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
