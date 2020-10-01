import React from 'react'
import { useValues, useActions } from 'kea'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_LINE_GRAPH_CUMULATIVE, STICKINESS } from '~/lib/constants'
import { chartFilterLogic } from './chartFilterLogic'
export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props

    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)
    return [
        (!filters.display ||
            filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
            filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) && (
            <Tooltip
                key="1"
                getPopupContainer={(trigger) => trigger.parentElement}
                placement="right"
                title="Click on a point to see users related to the datapoint"
            >
                <InfoCircleOutlined className="info" style={{ color: '#007bff' }}></InfoCircleOutlined>
            </Tooltip>
        ),

        <Select
            key="2"
            defaultValue={displayMap[filters.display || ACTIONS_LINE_GRAPH_LINEAR]}
            value={displayMap[chartFilter || ACTIONS_LINE_GRAPH_LINEAR]}
            onChange={(value) => {
                setChartFilter(value)
                onChange(value)
            }}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
        >
            <Select.OptGroup label={'Line Chart'}>
                <Select.Option
                    value={ACTIONS_LINE_GRAPH_LINEAR}
                    disabled={filters.session && filters.session === 'dist'}
                >
                    Linear
                </Select.Option>
                <Select.Option
                    value={ACTIONS_LINE_GRAPH_CUMULATIVE}
                    disabled={filters.session || filters.shown_as === STICKINESS}
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
