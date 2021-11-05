import React from 'react'
import { useActions, useValues } from 'kea'
import { Select } from 'antd'
import {
    AreaChartOutlined,
    BarChartOutlined,
    LineChartOutlined,
    PieChartOutlined,
    TableOutlined,
} from '@ant-design/icons'
import { ChartDisplayType, FunnelVizType, ViewType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

interface ChartFilterProps {
    onChange: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled: boolean
}

export function ChartFilter({ onChange, disabled }: ChartFilterProps): JSX.Element {
    const { filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)

    const linearDisabled = !!filters.session && filters.session === 'dist'
    const cumulativeDisabled =
        !!filters.session || filters.insight === ViewType.STICKINESS || filters.insight === ViewType.RETENTION
    const tableDisabled = false
    const pieDisabled =
        !!filters.session || filters.insight === ViewType.RETENTION || filters.insight === ViewType.STICKINESS
    const barDisabled = !!filters.session || filters.insight === ViewType.RETENTION
    const barValueDisabled =
        barDisabled || filters.insight === ViewType.STICKINESS || filters.insight === ViewType.RETENTION

    const defaultDisplay: ChartDisplayType =
        filters.insight === ViewType.RETENTION
            ? ChartDisplayType.ActionsTable
            : filters.insight === ViewType.FUNNELS
            ? ChartDisplayType.FunnelViz
            : ChartDisplayType.ActionsLineGraphLinear

    function Label({ icon, children = null }: { icon: React.ReactNode; children: React.ReactNode }): JSX.Element {
        return (
            <>
                {icon} {children}
            </>
        )
    }
    const options = [
        {
            label: 'Line Chart',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraphLinear,
                    label: <Label icon={<LineChartOutlined />}>Linear</Label>,
                    disabled: linearDisabled,
                },
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    label: <Label icon={<AreaChartOutlined />}>Cumulative</Label>,
                    disabled: cumulativeDisabled,
                },
            ],
        },
        {
            label: 'Bar Chart',
            options: [
                {
                    value: ChartDisplayType.ActionsBarChart,
                    label: <Label icon={<BarChartOutlined />}>Time</Label>,
                    disabled: barDisabled,
                },
                {
                    value: ChartDisplayType.ActionsBarChartValue,
                    label: <Label icon={<BarChartOutlined />}>Value</Label>,
                    disabled: barValueDisabled,
                },
            ],
        },
        {
            value: ChartDisplayType.ActionsTable,
            label: <Label icon={<TableOutlined />}>Table</Label>,
            disabled: tableDisabled,
        },
        {
            value: ChartDisplayType.ActionsPieChart,
            label: <Label icon={<PieChartOutlined />}>Pie</Label>,
            disabled: pieDisabled,
        },
    ]

    return (
        <Select
            value={filters.display || defaultDisplay}
            onChange={(value: ChartDisplayType) => {
                setFilters({ ...filters, display: value })
                onChange(value)
            }}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            disabled={disabled}
            options={options}
        />
    )
}
