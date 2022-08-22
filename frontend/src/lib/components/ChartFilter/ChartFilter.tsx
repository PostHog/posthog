import React from 'react'
import { useActions, useValues } from 'kea'
import { chartFilterLogic } from './chartFilterLogic'
import {
    AreaChartOutlined,
    BarChartOutlined,
    LineChartOutlined,
    OrderedListOutlined,
    PieChartOutlined,
    GlobalOutlined,
    TableOutlined,
    NumberOutlined,
} from '@ant-design/icons'
import { ChartDisplayType, FilterType, FunnelVizType, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { Tooltip } from '../Tooltip'
import { LemonTag } from '../LemonTag/LemonTag'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

interface ChartFilterProps {
    filters: FilterType
    onChange?: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled?: boolean
}

export function ChartFilter({ filters, onChange, disabled }: ChartFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { chartFilter } = useValues(chartFilterLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))

    const seriesCount = toLocalFilters(filters).length
    const cumulativeDisabled = filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const pieDisabled: boolean = filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION
    const worldMapDisabled: boolean =
        filters.insight === InsightType.STICKINESS ||
        (filters.insight === InsightType.RETENTION &&
            !!filters.breakdown &&
            filters.breakdown !== '$geoip_country_code' &&
            filters.breakdown !== '$geoip_country_name') ||
        seriesCount > 1 // World map only works with one series
    const boldNumberDisabled: boolean =
        filters.insight === InsightType.STICKINESS || filters.insight === InsightType.RETENTION || seriesCount > 1 // Bold number only works with one series
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
                <div className="w-full">
                    {icon} {children}
                </div>
            </Tooltip>
        )
    }

    const options: LemonSelectOptions<ChartDisplayType | FunnelVizType> =
        filters.insight === InsightType.FUNNELS
            ? [
                  { value: FunnelVizType.Steps, label: <Label icon={<OrderedListOutlined />}>Steps</Label> },
                  {
                      value: FunnelVizType.Trends,
                      label: (
                          <Label icon={<LineChartOutlined />}>
                              Trends
                              <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
                                  BETA
                              </LemonTag>
                          </Label>
                      ),
                  },
              ]
            : [
                  {
                      title: 'Line Chart',
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
                      title: 'Bar Chart',
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
                      options: [
                          {
                              value: ChartDisplayType.BoldNumber,
                              label: (
                                  <Label
                                      icon={<NumberOutlined />}
                                      tooltip="Big and bold. Only works with one series at a time."
                                  >
                                      Number
                                  </Label>
                              ),
                              disabled: boldNumberDisabled,
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
                          {
                              value: ChartDisplayType.WorldMap,
                              label: (
                                  <Label
                                      icon={<GlobalOutlined />}
                                      tooltip="Visualize data by country. Only works with one series at a time."
                                  >
                                      World Map
                                  </Label>
                              ),
                              disabled: worldMapDisabled,
                          },
                      ],
                  },
              ]
    return (
        <LemonSelect
            key="2"
            value={chartFilter || defaultDisplay || filters.display}
            onChange={(value) => {
                setChartFilter(value as ChartDisplayType | FunnelVizType)
                onChange?.(value as ChartDisplayType | FunnelVizType)
            }}
            dropdownPlacement={'bottom-end'}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            disabled={disabled}
            options={options}
            size={'small'}
        />
    )
}
