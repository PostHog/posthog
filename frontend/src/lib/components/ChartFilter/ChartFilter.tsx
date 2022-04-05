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
    GlobalOutlined,
    TableOutlined,
} from '@ant-design/icons'
import { ChartDisplayType, FilterType, FunnelVizType, InsightType } from '~/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { toLocalFilters } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { Tooltip } from '../Tooltip'

interface ChartFilterProps {
    filters: FilterType
    onChange?: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled: boolean
}

export function ChartFilter({ filters, onChange, disabled }: ChartFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { chartFilter } = useValues(chartFilterLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const cumulativeDisabled = filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const pieDisabled: boolean = filters.insight === InsightType.RETENTION || filters.insight === InsightType.STICKINESS
    const worldMapDisabled: boolean =
        filters.insight === InsightType.RETENTION ||
        filters.insight === InsightType.STICKINESS ||
        (!!filters.breakdown &&
            filters.breakdown !== '$geoip_country_code' &&
            filters.breakdown !== '$geoip_country_name') ||
        toLocalFilters(filters).length > 1
    const barDisabled: boolean = filters.insight === InsightType.RETENTION
    const barValueDisabled: boolean =
        barDisabled || filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const defaultDisplay: ChartDisplayType =
        filters.insight === InsightType.RETENTION
            ? ChartDisplayType.ActionsTable
            : filters.insight === InsightType.FUNNELS
            ? ChartDisplayType.FunnelViz
            : ChartDisplayType.ActionsLineGraph

    function Label({
        icon,
        tooltip,
        children = null,
    }: {
        icon: React.ReactNode
        tooltip?: string
        children: React.ReactNode
    }): JSX.Element {
        return (
            <Tooltip title={tooltip} placement="left">
                <div style={{ width: '100%' }}>
                    {icon} {children}
                </div>
            </Tooltip>
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
                              value: ChartDisplayType.ActionsLineGraph,
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
                              value: ChartDisplayType.ActionsBar,
                              label: <Label icon={<BarChartOutlined />}>Time</Label>,
                              disabled: barDisabled,
                          },
                          {
                              value: ChartDisplayType.ActionsBarValue,
                              label: <Label icon={<BarChartOutlined />}>Value</Label>,
                              disabled: barValueDisabled,
                          },
                      ],
                  },
                  {
                      value: ChartDisplayType.ActionsTable,
                      label: <Label icon={<TableOutlined />}>Table</Label>,
                  },
                  {
                      value: ChartDisplayType.ActionsPie,
                      label: <Label icon={<PieChartOutlined />}>Pie</Label>,
                      disabled: pieDisabled,
                  },
                  ...(featureFlags[FEATURE_FLAGS.HEDGEHOGGER]
                      ? [
                            {
                                value: ChartDisplayType.WorldMap,
                                label: (
                                    <Label
                                        icon={<GlobalOutlined />}
                                        tooltip="Visualize data by country. Only works with one series at a time."
                                    >
                                        Map
                                    </Label>
                                ),
                                disabled: worldMapDisabled,
                            },
                        ]
                      : []),
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
