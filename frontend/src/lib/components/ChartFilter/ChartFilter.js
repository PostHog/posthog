import React from 'react'
import { useValues, useActions } from 'kea'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_LINE_GRAPH_CUMULATIVE, STICKINESS, ACTIONS_TABLE } from '~/lib/constants'
import { chartFilterLogic } from './chartFilterLogic'

export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props

    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    const cumulativeDisabled = filters.session || filters.shown_as === STICKINESS || filters.retentionType
    const linearDisabled = filters.session && filters.session === 'dist'
    const tableDisabled = false
    const pieDisabled = filters.session || filters.retentionType
    const defaultDisplay = filters.retentionType ? ACTIONS_TABLE : ACTIONS_LINE_GRAPH_LINEAR

    return [
        (!filters.display ||
            filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
            filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) && (
            <Tooltip key="1" placement="right" title="Click on a point to see users related to the datapoint">
                <InfoCircleOutlined className="info-indicator" />
            </Tooltip>
        ),

        <Select
            key="2"
            defaultValue={displayMap[filters.display || defaultDisplay]}
            value={displayMap[chartFilter || defaultDisplay]}
            onChange={(value) => {
                setChartFilter(value)
                onChange(value)
            }}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
        >
            <Select.OptGroup label={'Line Chart'}>
                <Select.Option value={ACTIONS_LINE_GRAPH_LINEAR} disabled={linearDisabled}>
                    Linear
                </Select.Option>
                <Select.Option value={ACTIONS_LINE_GRAPH_CUMULATIVE} disabled={cumulativeDisabled}>
                    Cumulative
                </Select.Option>
            </Select.OptGroup>
            <Select.Option value="ActionsTable" disabled={tableDisabled}>
                Table
            </Select.Option>
            <Select.Option value="ActionsPie" disabled={pieDisabled}>
                Pie
            </Select.Option>
        </Select>,
    ]
}
