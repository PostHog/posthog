import React from 'react'
import { useActions, useValues } from 'kea'
import { Select, Tag } from 'antd'
import { chartFilterLogic } from './chartFilterLogic'
import {
    AreaChartOutlined,
    BarChartOutlined,
    LineChartOutlined,
    OrderedListOutlined,
    PieChartOutlined,
    TableOutlined,
} from '@ant-design/icons'
import { ChartDisplayType, FilterType, FunnelVizType, ViewType } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

interface ChartFilterProps {
    filters: FilterType
    onChange: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled: boolean
}

export function ChartFilter({ filters, onChange, disabled }: ChartFilterProps): JSX.Element {
    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)
    const { preflight } = useValues(preflightLogic)

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

    function WarningTag({ children = null }: { children: React.ReactNode }): JSX.Element {
        return (
            <Tag color="orange" style={{ marginLeft: 8, fontSize: 10 }}>
                {children}
            </Tag>
        )
    }

    const options =
        filters.insight === ViewType.FUNNELS
            ? preflight?.is_clickhouse_enabled
                ? [
                      {
                          value: FunnelVizType.Steps,
                          label: <Label icon={<OrderedListOutlined />}>Steps</Label>,
                      },
                      {
                          value: FunnelVizType.Trends,
                          label: (
                              <Label icon={<LineChartOutlined />}>
                                  Trends
                                  <WarningTag>BETA</WarningTag>
                              </Label>
                          ),
                      },
                  ]
                : [
                      {
                          value: FunnelVizType.Steps,
                          label: <Label icon={<OrderedListOutlined />}>Steps</Label>,
                      },
                  ]
            : [
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
            key="2"
            defaultValue={filters.display || defaultDisplay}
            value={chartFilter || defaultDisplay}
            onChange={(value: ChartDisplayType | FunnelVizType) => {
                setChartFilter(value)
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
