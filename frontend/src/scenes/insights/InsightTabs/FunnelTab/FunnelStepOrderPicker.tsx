import React from 'react'
import { StepOrderValue } from '~/types'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'

interface StepOption {
    key?: string
    label: string
    value: StepOrderValue
    copy: string
}

const options: StepOption[] = [
    {
        label: 'Sequential',
        value: StepOrderValue.ORDERED,
        copy: "Step B must happen after Step A, but the previous step doesn't have to be step A.",
    },
    {
        label: 'Strict Order',
        value: StepOrderValue.STRICT,
        copy: 'Step B must happen directly after Step A.',
    },
    {
        label: 'Any Order',
        value: StepOrderValue.UNORDERED,
        copy: 'Steps can be completed in any sequence.',
    },
]

export function FunnelStepOrderPicker(): JSX.Element {
    const { filters } = useValues(funnelLogic)
    const { setFilters } = useActions(funnelLogic)

    return (
        <Select
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            defaultValue={StepOrderValue.ORDERED}
            value={filters.funnel_order_type || StepOrderValue.ORDERED}
            onSelect={(stepOrder) => setFilters({ funnel_order_type: stepOrder })}
            listHeight={440}
            bordered={false}
            dropdownMatchSelectWidth={false}
            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
            optionLabelProp="label"
        >
            <Select.OptGroup label="Step Order">
                {options.map((option) => {
                    return (
                        <Select.Option key={option.value} value={option.value}>
                            <Tooltip title={option.copy}>{option.label}</Tooltip>
                        </Select.Option>
                    )
                })}
            </Select.OptGroup>
        </Select>
    )
}
