import React from 'react'
import { Select } from 'antd'

export function ChartFilter(props) {
    let { onChange, defaultValue, disabledOptions } = props
    return (
        <Select defaultValue={defaultValue} onChange={onChange} bordered={false} dropdownMatchSelectWidth={false}>
            <Select.Option value="ActionsLineGraph" disabled={(disabledOptions || []).includes('ActionsLineGraph')}>
                Line chart
            </Select.Option>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={(disabledOptions || []).includes('ActionsPie')}>
                Pie
            </Select.Option>
        </Select>
    )
}
