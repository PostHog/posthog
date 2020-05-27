import React from 'react'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'

export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props
    return [
        (!filters.display || filters.display === 'ActionsLineGraph') && (
            <Tooltip
                key="1"
                getPopupContainer={trigger => trigger.parentElement}
                placement="right"
                title="Click on a point to see users related to the datapoint"
            >
                <InfoCircleOutlined className="info" style={{ color: '#007bff' }}></InfoCircleOutlined>
            </Tooltip>
        ),

        <Select
            key="2"
            defaultValue={displayMap[filters.display || 'ActionsLineGraph']}
            value={displayMap[filters.display || 'ActionsLineGraph']}
            onChange={onChange}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
        >
            <Select.Option value="ActionsLineGraph" disabled={filters.session && filters.session == 'dist'}>
                Line chart
            </Select.Option>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={filters.session}>
                Pie
            </Select.Option>
        </Select>,
    ]
}
