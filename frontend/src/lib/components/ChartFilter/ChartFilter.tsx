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
import { Tooltip } from '../Tooltip'
import { LemonTag } from '../LemonTag/LemonTag'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { isRetentionFilter, isStickinessFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

interface ChartFilterProps {
    filters: FilterType
    onChange?: (chartFilter: ChartDisplayType | FunnelVizType) => void
    disabled?: boolean
}

export function ChartFilter({ filters, onChange, disabled }: ChartFilterProps): JSX.Element {
    const { insightProps, isSingleSeries } = useValues(insightLogic)
    const { chartFilter } = useValues(chartFilterLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))

    const cumulativeDisabled = isStickinessFilter(filters) || isRetentionFilter(filters)
    const pieDisabled: boolean = isStickinessFilter(filters) || isRetentionFilter(filters)
    const worldMapDisabled: boolean =
        isStickinessFilter(filters) ||
        (isRetentionFilter(filters) &&
            !!filters.breakdown &&
            filters.breakdown !== '$geoip_country_code' &&
            filters.breakdown !== '$geoip_country_name') ||
        !isSingleSeries || // World map only works with one series
        (isTrendsFilter(filters) && !!filters.formula) // Breakdowns currently don't work with formulas
    const boldNumberDisabled: boolean = isStickinessFilter(filters) || isRetentionFilter(filters) || !isSingleSeries // Bold number only works with one series
    const barDisabled: boolean = isRetentionFilter(filters)
    const barValueDisabled: boolean = barDisabled || isStickinessFilter(filters) || isRetentionFilter(filters)
    const defaultDisplay: ChartDisplayType = isRetentionFilter(filters)
        ? ChartDisplayType.ActionsTable
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
                              <LemonTag
                                  type="warning"
                                  className="uppercase"
                                  style={{ marginLeft: 6, lineHeight: '1.4em' }}
                              >
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
            value={chartFilter || defaultDisplay}
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
