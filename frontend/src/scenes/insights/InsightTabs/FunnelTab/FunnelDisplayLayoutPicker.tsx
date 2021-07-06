import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelPlotOutlined, BarChartOutlined } from '@ant-design/icons'
import { FunnelBarLayout } from 'lib/constants'

export function FunnelDisplayLayoutPicker(): JSX.Element {
    const { barGraphLayout } = useValues(funnelLogic)
    const { setBarGraphLayout } = useActions(funnelLogic)
    const options = [
        {
            value: FunnelBarLayout.vertical,
            icon: <BarChartOutlined />,
            label: 'Left to right',
        },
        {
            value: FunnelBarLayout.horizontal,
            icon: <FunnelPlotOutlined />,
            label: 'Top to bottom',
        },
    ]
    return (
        <Select
            defaultValue={FunnelBarLayout.vertical}
            value={barGraphLayout || FunnelBarLayout.vertical}
            onChange={setBarGraphLayout}
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
