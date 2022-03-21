import React from 'react'
import { StepOrderValue } from '~/types'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

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
        label: 'Strict Order',
        value: StepOrderValue.STRICT,
    },
    {
        label: 'Any Order',
        value: StepOrderValue.UNORDERED,
    },
]

export function FunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return (
        <Select
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            defaultValue={StepOrderValue.ORDERED}
            value={filters.funnel_order_type || StepOrderValue.ORDERED}
            onSelect={(stepOrder) => setFilters({ funnel_order_type: stepOrder })}
            listHeight={440}
            dropdownMatchSelectWidth={false}
            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
            optionLabelProp="label"
            options={options}
            style={{ marginRight: 4 }}
        />
    )
}
