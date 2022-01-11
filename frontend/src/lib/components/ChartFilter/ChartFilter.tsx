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
import { ChartDisplayType, FilterType, FunnelVizType, InsightType } from '~/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

interface ChartFilterProps {
    filters: FilterType
    onChange?: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled: boolean
}

export function ChartFilter({ filters, onChange, disabled }: ChartFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { chartFilter } = useValues(chartFilterLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))

    const cumulativeDisabled = filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const tableDisabled = false
    const pieDisabled = filters.insight === InsightType.RETENTION || filters.insight === InsightType.STICKINESS
    const barDisabled = filters.insight === InsightType.RETENTION
    const barValueDisabled =
        barDisabled || filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const defaultDisplay: ChartDisplayType =
        filters.insight === InsightType.RETENTION
            ? ChartDisplayType.ActionsTable
            : filters.insight === InsightType.FUNNELS
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
        filters.insight === InsightType.FUNNELS
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
                      label: 'Line Chart',
                      options: [
                          {
                              value: ChartDisplayType.ActionsLineGraphLinear,
                              label: <Label icon={<LineChartOutlined />}>Linear</Label>,
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
                onChange?.(value)
            }}
            bordered
            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            disabled={disabled}
            options={options}
        />
    )
}
