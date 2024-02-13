import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import {
    Icon123,
    IconAreaChart,
    IconBarChart,
    IconCumulativeChart,
    IconPieChart,
    IconPublic,
    IconShowChart,
    IconTableChart,
} from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

export function ChartFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const { isTrends, isSingleSeries, formula, breakdownFilter } = useValues(insightVizDataLogic(insightProps))

    const trendsOnlyDisabledReason = !isTrends ? 'This type is only available in Trends.' : undefined
    const singleSeriesOnlyDisabledReason = !isSingleSeries
        ? 'This type currently only supports insights with one series, and this insight has multiple series.'
        : undefined

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconShowChart />,
                    label: 'Line chart',
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconBarChart />,
                    label: 'Bar chart',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                },
            ],
        },
        {
            title: 'Cumulative time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    icon: <IconCumulativeChart />,
                    label: 'Line chart (cumulative)',
                    labelInMenu: 'Line chart',
                    disabledReason: trendsOnlyDisabledReason,
                },
            ],
        },
        {
            title: 'Total value',
            options: [
                {
                    value: ChartDisplayType.BoldNumber,
                    icon: <Icon123 />,
                    label: 'Number',
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconBarChart className="rotate-90" />,
                    label: 'Bar chart',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                },
                {
                    value: ChartDisplayType.WorldMap,
                    icon: <IconPublic />,
                    label: 'World map',
                    tooltip: 'Visualize data by country.',
                    disabledReason:
                        trendsOnlyDisabledReason ||
                        (formula
                            ? "This type isn't available, because it doesn't support formulas."
                            : !!breakdownFilter?.breakdown &&
                              breakdownFilter.breakdown !== '$geoip_country_code' &&
                              breakdownFilter.breakdown !== '$geoip_country_name'
                            ? "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties."
                            : undefined),
                },
            ],
        },
    ]

    return (
        <LemonSelect
            key="2"
            value={display || ChartDisplayType.ActionsLineGraph}
            onChange={(value) => {
                updateInsightFilter({ display: value })
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={options}
            size="small"
        />
    )
}
