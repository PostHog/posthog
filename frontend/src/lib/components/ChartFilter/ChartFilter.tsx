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
} from '@ant-design/icons'
import { ChartDisplayType, FilterType, FunnelVizType, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { Tooltip } from '../Tooltip'
import { LemonTag } from '../LemonTag/LemonTag'
import { LemonSelect, LemonSelectOptions, LemonSelectSection } from '@posthog/lemon-ui'

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

    const options: LemonSelectOptions | LemonSelectSection<LemonSelectOptions>[] =
        filters.insight === InsightType.FUNNELS
            ? {
                  [FunnelVizType.Steps]: {
                      label: <Label icon={<OrderedListOutlined />}>Steps</Label>,
                  },
                  [FunnelVizType.Trends]: {
                      label: (
                          <Label icon={<LineChartOutlined />}>
                              Trends
                              <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
                                  BETA
                              </LemonTag>
                          </Label>
                      ),
                  },
              }
            : [
                  {
                      label: 'Line Chart',
                      options: {
                          [ChartDisplayType.ActionsLineGraph]: {
                              label: <Label icon={<LineChartOutlined />}>Linear</Label>,
                          },
                          [ChartDisplayType.ActionsLineGraphCumulative]: {
                              label: <Label icon={<AreaChartOutlined />}>Cumulative</Label>,
                              disabled: cumulativeDisabled,
                          },
                      },
                  },
                  {
                      label: 'Bar Chart',
                      options: {
                          [ChartDisplayType.ActionsBar]: {
                              label: <Label icon={<BarChartOutlined />}>Time</Label>,
                              disabled: barDisabled,
                          },
                          [ChartDisplayType.ActionsBarValue]: {
                              label: <Label icon={<BarChartOutlined />}>Value</Label>,
                              disabled: barValueDisabled,
                          },
                      },
                  },
                  {
                      label: '',
                      options: {
                          [ChartDisplayType.ActionsTable]: {
                              label: <Label icon={<TableOutlined />}>Table</Label>,
                          },
                          [ChartDisplayType.ActionsPie]: {
                              label: <Label icon={<PieChartOutlined />}>Pie</Label>,
                              disabled: pieDisabled,
                          },
                          [ChartDisplayType.WorldMap]: {
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
                      },
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
            outlined
            dropdownPlacement={'bottom-end'}
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            disabled={disabled}
            options={options}
            type={'stealth'}
            size={'small'}
        />
    )
}
