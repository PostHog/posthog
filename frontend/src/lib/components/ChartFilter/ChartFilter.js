import React from 'react'
import { useValues, useActions } from 'kea'
import { Select, Tag } from 'antd'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_PIE_CHART,
    ACTIONS_BAR_CHART,
    ACTIONS_TABLE,
    FUNNEL_VIZ,
    ACTIONS_BAR_CHART_VALUE,
} from '~/lib/constants'
import { chartFilterLogic } from './chartFilterLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import {
    OrderedListOutlined,
    LineChartOutlined,
    AreaChartOutlined,
    BarChartOutlined,
    TableOutlined,
    PieChartOutlined,
} from '@ant-design/icons'

export function ChartFilter(props) {
    let { filters, onChange } = props

    const { chartFilter } = useValues(chartFilterLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    const linearDisabled = filters.session && filters.session === 'dist'
    const cumulativeDisabled =
        filters.session || filters.insight === ViewType.STICKINESS || filters.insight === ViewType.RETENTION
    const tableDisabled = false
    const pieDisabled = filters.session || filters.insight === ViewType.RETENTION
    const barDisabled = filters.session || filters.insight === ViewType.RETENTION
    const barValueDisabled =
        barDisabled || filters.insight === ViewType.STICKINESS || filters.insight === ViewType.RETENTION
    const defaultDisplay =
        filters.insight === ViewType.RETENTION
            ? ACTIONS_TABLE
            : filters.insight === ViewType.FUNNELS
            ? FUNNEL_VIZ
            : ACTIONS_LINE_GRAPH_LINEAR

    function Label({ icon, children = null }) {
        return (
            <>
                {icon} {children}
            </>
        )
    }

    const options =
        filters.insight === ViewType.FUNNELS
            ? [
                  {
                      value: FUNNEL_VIZ,
                      label: <Label icon={<OrderedListOutlined />}>Steps</Label>,
                  },
                  {
                      value: ACTIONS_LINE_GRAPH_LINEAR,
                      label: (
                          <Label icon={<LineChartOutlined />}>
                              Trends
                              <Tag color="orange" style={{ marginLeft: 8, fontSize: 10 }}>
                                  BETA
                              </Tag>
                          </Label>
                      ),
                  },
              ]
            : [
                  {
                      label: 'Line Chart',
                      options: [
                          {
                              value: ACTIONS_LINE_GRAPH_LINEAR,
                              label: <Label icon={<LineChartOutlined />}>Linear</Label>,
                              disabled: linearDisabled,
                          },
                          {
                              value: ACTIONS_LINE_GRAPH_CUMULATIVE,
                              label: <Label icon={<AreaChartOutlined />}>Cumulative</Label>,
                              disabled: cumulativeDisabled,
                          },
                      ],
                  },
                  {
                      label: 'Bar Chart',
                      options: [
                          {
                              value: ACTIONS_BAR_CHART,
                              label: <Label icon={<BarChartOutlined />}>Time</Label>,
                              disabled: barDisabled,
                          },
                          {
                              value: ACTIONS_BAR_CHART_VALUE,
                              label: <Label icon={<BarChartOutlined />}>Value</Label>,
                              disabled: barValueDisabled,
                          },
                      ],
                  },
                  {
                      value: ACTIONS_TABLE,
                      label: <Label icon={<TableOutlined />}>Table</Label>,
                      disabled: tableDisabled,
                  },
                  {
                      value: ACTIONS_PIE_CHART,
                      label: <Label icon={<PieChartOutlined />}>Pie</Label>,
                      disabled: pieDisabled,
                  },
              ]
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
            options={options}
        />
    )
}
