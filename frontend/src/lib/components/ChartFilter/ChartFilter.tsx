import { useActions, useValues } from 'kea'
import { chartFilterLogic } from './chartFilterLogic'
import {
    IconShowChart,
    IconCumulativeChart,
    IconBarChart,
    IconAreaChart,
    Icon123,
    IconPieChart,
    IconTableChart,
    IconPublic,
} from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ChartFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { chartFilter } = useValues(chartFilterLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))

    const { isTrends, isSingleSeries, formula, breakdown } = useValues(insightVizDataLogic(insightProps))

    const trendsOnlyDisabledReason = !isTrends ? 'This type is only available in Trends.' : undefined
    const singleSeriesOnlyDisabledReason = !isSingleSeries
        ? 'This type currently only supports insights with one series, and this insight has multiple series.'
        : undefined

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Time Series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconShowChart />,
                    label: 'Line',
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconBarChart />,
                    label: 'Bar',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area',
                },
            ],
        },
        {
            title: 'Cumulative Time Series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    icon: <IconCumulativeChart />,
                    label: 'Line',
                    disabledReason: trendsOnlyDisabledReason,
                },
            ],
        },
        {
            title: 'Total Value',
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
                    label: 'Pie',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconBarChart className="rotate-90" />,
                    label: 'Bar',
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
                    label: 'World Map',
                    tooltip: 'Visualize data by country.',
                    disabledReason:
                        trendsOnlyDisabledReason ||
                        (formula
                            ? "This type isn't available, because it doesn't support formulas."
                            : !!breakdown?.breakdown &&
                              breakdown.breakdown !== '$geoip_country_code' &&
                              breakdown.breakdown !== '$geoip_country_name'
                            ? "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties."
                            : undefined),
                },
            ],
        },
    ]

    return (
        <>
            <span>Chart type</span>
            <LemonSelect
                key="2"
                value={chartFilter || ChartDisplayType.ActionsLineGraph}
                onChange={(value) => {
                    setChartFilter(value as ChartDisplayType)
                }}
                dropdownPlacement="bottom-end"
                optionTooltipPlacement="left"
                dropdownMatchSelectWidth={false}
                data-attr="chart-filter"
                options={options}
                size="small"
            />
        </>
    )
}
