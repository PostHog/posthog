import React from 'react'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'

export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props
    return [
        (!filters.display ||
            filters.display === 'ActionsLineGraphLinear' ||
            filters.display === 'ActionsLineGraphCumulative') && (
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
            defaultValue={displayMap[filters.display || 'ActionsLineGraphLinear']}
            value={displayMap[filters.display || 'ActionsLineGraphLinear']}
            onChange={onChange}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
        >
            <Select.OptGroup label="Line chart">
                <Select.Option value="ActionsLineGraphLinear" disabled={filters.session && filters.session === 'dist'}>
                    Linear
                </Select.Option>
                <Select.Option
                    value="ActionsLineGraphCumulative"
                    disabled={filters.session || filters.shown_as === 'Stickiness'}
                >
                    Cumulative
                </Select.Option>
            </Select.OptGroup>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={filters.session}>
                Pie
            </Select.Option>
        </Select>,
    ]
}
