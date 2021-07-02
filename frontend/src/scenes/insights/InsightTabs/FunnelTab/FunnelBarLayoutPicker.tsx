import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelPlotOutlined, BarChartOutlined } from '@ant-design/icons'
import { FunnelBarLayout } from 'scenes/funnels/FunnelBarGraph'

export default function FunnelBarLayoutPicker(): JSX.Element {
    const { barGraphLayout } = useValues(funnelLogic)
    const { setBarGraphLayout } = useActions(funnelLogic)
    const options = [
        {
            value: FunnelBarLayout.horizontal,
            label: (
                <>
                    <FunnelPlotOutlined /> Top to bottom
                </>
            ),
        },
        {
            value: FunnelBarLayout.vertical,
            label: (
                <>
                    <BarChartOutlined /> Left to right
                </>
            ),
        },
    ]
    return (
        <Select
            defaultValue={FunnelBarLayout.horizontal}
            value={barGraphLayout || FunnelBarLayout.horizontal}
            onChange={setBarGraphLayout}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            options={options}
        />
    )
}
