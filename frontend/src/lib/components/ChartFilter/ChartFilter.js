import React from 'react'
import { useValues, useActions } from 'kea'
import { Select } from 'antd'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    STICKINESS,
    ACTIONS_PIE_CHART,
    ACTIONS_BAR_CHART,
    ACTIONS_TABLE,
    LIFECYCLE,
} from '~/lib/constants'
import { chartFilterLogic } from './chartFilterLogic'
import { ViewType } from 'scenes/insights/insightLogic'

export function ChartFilter(props) {
    let { filters, displayMap, onChange } = props

    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    const cumulativeDisabled = filters.session || filters.shown_as === STICKINESS || filters.retentionType
    const linearDisabled = filters.session && filters.session === 'dist'
    const tableDisabled = false
    const pieDisabled = filters.session || filters.insight === ViewType.RETENTION
    const defaultDisplay = filters.retentionType ? ACTIONS_TABLE : ACTIONS_LINE_GRAPH_LINEAR

    return (
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
            disabled={filters.shown_as === LIFECYCLE}
        >
            <Select.OptGroup label={'Line Chart'}>
                <Select.Option value={ACTIONS_LINE_GRAPH_LINEAR} disabled={linearDisabled}>
                    Linear
                </Select.Option>
                <Select.Option value={ACTIONS_LINE_GRAPH_CUMULATIVE} disabled={cumulativeDisabled}>
                    Cumulative
                </Select.Option>
            </Select.OptGroup>
            <Select.Option value={ACTIONS_TABLE} disabled={tableDisabled}>
                Table
            </Select.Option>
            <Select.Option value={ACTIONS_PIE_CHART} disabled={pieDisabled}>
                Pie
            </Select.Option>
            <Select.Option value={ACTIONS_BAR_CHART} disabled={filters.session || filters.retentionType}>
                Bar
            </Select.Option>
        </Select>
    )
}
