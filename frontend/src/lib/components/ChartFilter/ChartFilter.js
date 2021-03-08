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
    FUNNEL_VIZ,
    ACTIONS_BAR_CHART_VALUE,
} from '~/lib/constants'
import { chartFilterLogic } from './chartFilterLogic'
import { ViewType } from 'scenes/insights/insightLogic'

export function ChartFilter(props) {
    let { filters, onChange } = props

    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    const linearDisabled = filters.session && filters.session === 'dist'
    const cumulativeDisabled =
        filters.session || filters.shown_as === STICKINESS || filters.insight === ViewType.RETENTION
    const tableDisabled = false
    const pieDisabled = filters.session || filters.insight === ViewType.RETENTION
    const barDisabled = filters.session || filters.insight === ViewType.RETENTION
    const barValueDisabled = barDisabled || filters.shown_as === STICKINESS || filters.insight === ViewType.RETENTION
    const defaultDisplay =
        filters.insight === ViewType.RETENTION
            ? ACTIONS_TABLE
            : filters.insight === ViewType.FUNNELS
            ? FUNNEL_VIZ
            : ACTIONS_LINE_GRAPH_LINEAR

    return (
        <Select
            key="2"
            defaultValue={filters.display || defaultDisplay}
            value={chartFilter || defaultDisplay}
            onChange={(value) => {
                setChartFilter(value)
                onChange(value)
            }}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            disabled={props.disabled}
        >
            {filters.insight === ViewType.FUNNELS ? (
                <>
                    <Select.Option value={FUNNEL_VIZ}>Steps</Select.Option>
                    <Select.Option value={ACTIONS_LINE_GRAPH_LINEAR}>Trends</Select.Option>
                </>
            ) : (
                <>
                    <Select.OptGroup label={'Line Chart'}>
                        <Select.Option value={ACTIONS_LINE_GRAPH_LINEAR} disabled={linearDisabled}>
                            Linear
                        </Select.Option>
                        <Select.Option value={ACTIONS_LINE_GRAPH_CUMULATIVE} disabled={cumulativeDisabled}>
                            Cumulative
                        </Select.Option>
                    </Select.OptGroup>
                    <Select.OptGroup label={'Bar Chart'}>
                        <Select.Option value={ACTIONS_BAR_CHART} disabled={barDisabled}>
                            Time
                        </Select.Option>
                        <Select.Option value={ACTIONS_BAR_CHART_VALUE} disabled={barValueDisabled}>
                            Value
                        </Select.Option>
                    </Select.OptGroup>
                    <Select.Option value={ACTIONS_TABLE} disabled={tableDisabled}>
                        Table
                    </Select.Option>
                    <Select.Option value={ACTIONS_PIE_CHART} disabled={pieDisabled}>
                        Pie
                    </Select.Option>
                </>
            )}
        </Select>
    )
}
