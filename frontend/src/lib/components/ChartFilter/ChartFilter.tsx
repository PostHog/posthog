import { IconGlobe, IconGraph, IconPieChart, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Icon123, IconAreaChart, IconCumulativeChart, IconTableChart } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

function ChartFilterOptionLabel(props: { label: string; description?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{props.label}</span>
            <span className="text-xs text-tertiary font-normal">{props.description}</span>
        </div>
    )
}

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
                        <ChartFilterOptionLabel
                            label="Line chart"
                            description="Trends over time plotted as a continuous line."
                        />
                    ),
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    labelInMenu: (
                        <ChartFilterOptionLabel
                            label="Area chart"
                            description="Trends over time plotted as a shaded area."
                        />
                    ),
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    labelInMenu: (
                        <ChartFilterOptionLabel label="Bar chart" description="Trends over time as vertical bars." />
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
                    disabledReason: trendsOnlyDisabledReason,
                    labelInMenu: (
                        <ChartFilterOptionLabel
                            label="Line chart (cumulative)"
                            description="Accumulating values over time as a continuous line."
                        />
                    ),
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
                        <ChartFilterOptionLabel label="Number" description="A big number showing the total value." />
                    ),
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                    disabledReason: trendsOnlyDisabledReason,
                    labelInMenu: (
                        <ChartFilterOptionLabel label="Pie chart" description="Proportions of a whole as a pie." />
                    ),
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconGraph className="rotate-90" />,
                    label: 'Bar chart',
                    disabledReason: trendsOnlyDisabledReason,
                    labelInMenu: (
                        <ChartFilterOptionLabel label="Bar chart" description="Total values as horizontal bars." />
                    ),
                },
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                    labelInMenu: <ChartFilterOptionLabel label="Table" description="Total values in a table view." />,
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
                        <ChartFilterOptionLabel label="World map" description="Values per country on a map." />
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
