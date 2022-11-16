import { useActions, useValues } from 'kea'
import { chartFilterLogic } from './chartFilterLogic'
import {
    IconShowChart,
    IconCumulativeChart,
    IconBarChart,
    Icon123,
    IconPieChart,
    IconTableChart,
    IconPublic,
} from 'lib/components/icons'

import { ChartDisplayType, FilterType, FunnelVizType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Tooltip } from '../Tooltip'
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
                <div className="flex items-center">
                    {icon}&nbsp;{children}
                </div>
            </Tooltip>
        )
    }

    const options: LemonSelectOptions<ChartDisplayType | FunnelVizType> = [
        {
            title: 'Time Series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    label: <Label icon={<IconShowChart />}>Line</Label>,
                },
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    label: <Label icon={<IconCumulativeChart />}>Cumulative</Label>,
                    disabled: cumulativeDisabled,
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    label: <Label icon={<IconBarChart />}>Bar</Label>,
                    disabled: barDisabled,
                },
            ],
        },
        {
            title: 'Value',
            options: [
                {
                    value: ChartDisplayType.BoldNumber,
                    label: (
                        <Label icon={<Icon123 />} tooltip="Big and bold. Only works with one series at a time.">
                            Number
                        </Label>
                    ),
                    disabled: boldNumberDisabled,
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    label: <Label icon={<IconPieChart />}>Pie</Label>,
                    disabled: pieDisabled,
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    label: <Label icon={<IconBarChart className="rotate-90" />}>Bar</Label>,
                    disabled: barValueDisabled,
                },
                {
                    value: ChartDisplayType.ActionsTable,
                    label: <Label icon={<IconTableChart fontSize="14" />}>Table</Label>,
                },
                {
                    value: ChartDisplayType.WorldMap,
                    label: (
                        <Label
                            icon={<IconPublic />}
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
