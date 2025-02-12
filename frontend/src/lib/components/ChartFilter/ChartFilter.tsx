import { IconGlobe, IconGraph, IconPieChart, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Icon123, IconAreaChart, IconCumulativeChart, IconTableChart } from 'lib/lemon-ui/icons'
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
                    icon: <IconTrends />,
                    label: 'Line chart',
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Line chart</span>
                            <span className="text-xs text-tertiary">Trends over time with a continuous line.</span>
                        </div>
                    ),
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Bar chart</span>
                            <span className="text-xs text-tertiary">Time-based data with vertical bars.</span>
                        </div>
                    ),
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Area chart</span>
                            <span className="text-xs text-tertiary">Trends over time with a shaded area.</span>
                        </div>
                    ),
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
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Line chart (cumulative)</span>
                            <span className="text-xs text-tertiary">Accumulating values over time.</span>
                        </div>
                    ),
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
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Number</span>
                            <span className="text-xs text-tertiary">A big number showing the total value..</span>
                        </div>
                    ),
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                    disabledReason: trendsOnlyDisabledReason,
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Pie chart</span>
                            <span className="text-xs text-tertiary">Proportions of a whole.</span>
                        </div>
                    ),
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconGraph className="rotate-90" />,
                    label: 'Bar chart',
                    disabledReason: trendsOnlyDisabledReason,
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Bar chart</span>
                            <span className="text-xs text-tertiary">Category totals with horizontal bars.</span>
                        </div>
                    ),
                },
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>Table</span>
                            <span className="text-xs text-tertiary">A table view of values.</span>
                        </div>
                    ),
                },
                {
                    value: ChartDisplayType.WorldMap,
                    icon: <IconGlobe />,
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
                    labelInMenu: (
                        <div className="flex flex-col gap-[2px]">
                            <span>World map</span>
                            <span className="text-xs text-tertiary">Data across regions using color or markers.</span>
                        </div>
                    ),
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
