import React from 'react'
import { Select } from 'antd'

export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props
    return (
        <Select
            defaultValue={displayMap[filters.display || 'ActionsLineGraph']}
            value={displayMap[filters.display || 'ActionsLineGraph']}
            onChange={onChange}
            bordered={false}
            dropdownMatchSelectWidth={false}
        >
            <Select.Option value="ActionsLineGraph" disabled={filters.breakdown || filters.session}>
                Line chart
            </Select.Option>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={filters.breakdown || filters.session}>
                Pie
            </Select.Option>
        </Select>
    )
}
