import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelPlotOutlined, BarChartOutlined } from '@ant-design/icons'
import { FunnelLayout } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelDisplayLayoutPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { barGraphLayout } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const options = [
        {
            value: FunnelLayout.vertical,
            icon: <BarChartOutlined />,
            label: 'Left to right',
        },
        {
            value: FunnelLayout.horizontal,
            icon: <FunnelPlotOutlined />,
            label: 'Top to bottom',
        },
    ]
    return (
        <Select
            defaultValue={FunnelLayout.vertical}
            value={barGraphLayout || FunnelLayout.vertical}
            onChange={(layout: FunnelLayout) => setFilters({ layout })}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            optionLabelProp="label"
        >
            <Select.OptGroup label="Graph display options">
                {options.map((option) => (
                    <Select.Option
                        key={option.value}
                        value={option.value}
                        label={
                            <>
                                {option.icon} {option.label}
                            </>
                        }
                    >
                        {option.label}
                    </Select.Option>
                ))}
            </Select.OptGroup>
        </Select>
    )
}
