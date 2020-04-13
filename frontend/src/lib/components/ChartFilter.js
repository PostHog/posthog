import React from 'react'
import { Select } from 'antd'

export function ChartFilter(props) {
    let { filters, displayMap, style, onChange } = props
    return (
        <Select
            defaultValue={displayMap[filters.display || 'ActionsLineGraph']}
            value={displayMap[filters.display || 'ActionsLineGraph']}
            onChange={onChange}
            style={style}
        >
            <Select.Option value="ActionsLineGraph" disabled={filters.breakdown}>
                Line chart
            </Select.Option>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={filters.breakdown}>
                Pie
            </Select.Option>
        </Select>
    )
}
