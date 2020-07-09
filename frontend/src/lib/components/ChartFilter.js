import React from 'react'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_LINE_GRAPH_STACKED,
    ACTIONS_LINE_GRAPH_CUMULATIVE_STACKED,
    STICKINESS,
} from '~/lib/constants'
export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props
    return [
        (!filters.display ||
            filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
            filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE ||
            filters.display === ACTIONS_LINE_GRAPH_STACKED ||
            filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE_STACKED) && (
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
            value={displayMap[filters.display || ACTIONS_LINE_GRAPH_LINEAR]}
            onChange={onChange}
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
                <Select.Option
                    value={ACTIONS_LINE_GRAPH_STACKED}
                    disabled={filters.session && filters.session === 'dist'}
                >
                    Stacked
                </Select.Option>
                <Select.Option
                    value={ACTIONS_LINE_GRAPH_CUMULATIVE_STACKED}
                    disabled={filters.session || filters.shown_as === STICKINESS}
                >
                    Cumulative Stacked
                </Select.Option>
            </Select.OptGroup>
            <Select.Option value="ActionsTable">Table</Select.Option>
            <Select.Option value="ActionsPie" disabled={filters.session}>
                Pie
            </Select.Option>
        </Select>,
    ]
}
