import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconGlobe, IconGraph, IconPieChart, IconRetentionHeatmap, IconTrends } from '@posthog/icons'
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart, IconCumulativeChart, IconTableChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

interface ChartOption {
    value: ChartDisplayType
    icon: ReactNode
    label: string
    description: string
    disabledReason?: string
}

interface ChartOptionGroup {
    title: string
    options: ChartOption[]
}

export function ChartFilterNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const { isTrends, isSingleSeriesOutput, formula, breakdownFilter } = useValues(insightVizDataLogic(insightProps))

    const trendsOnlyDisabledReason = !isTrends ? 'This type is only available in Trends.' : undefined
    const singleSeriesOnlyDisabledReason = !isSingleSeriesOutput
        ? 'This type currently only supports insights with one series, and this insight has multiple series.'
        : undefined

    const groups: ChartOptionGroup[] = [
        {
            title: 'Time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconTrends />,
                    label: 'Line chart',
                    description: 'Trends over time plotted as a continuous line.',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    description: 'Trends over time plotted as a shaded area.',
                },
                {
                    value: ChartDisplayType.ActionsUnstackedBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    description: 'Trends over time as vertical bars side-by-side.',
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Stacked bar chart',
                    description: 'Trends over time as vertical bars.',
                },
                ...(featureFlags[FEATURE_FLAGS.BOX_PLOT_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.BoxPlot,
                              icon: <IconGraph />,
                              label: 'Box plot',
                              description: 'Distribution of a property over time showing quartiles.',
                              disabledReason: trendsOnlyDisabledReason,
                          },
                      ]
                    : []),
                ...(featureFlags[FEATURE_FLAGS.SLOPE_GRAPH_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.SlopeGraph,
                              icon: <IconTrends />,
                              label: 'Slope graph',
                              description: 'Change from the start to the end of the range, one line per series.',
                              disabledReason: trendsOnlyDisabledReason,
                          },
                      ]
                    : []),
            ],
        },
        {
            title: 'Cumulative time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    icon: <IconCumulativeChart />,
                    label: 'Line chart (cumulative)',
                    description: 'Accumulating values over time as a continuous line.',
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
                    description: 'A big number showing the total value.',
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
                ...(featureFlags[FEATURE_FLAGS.METRIC_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.Metric,
                              icon: <IconTrends />,
                              label: 'Metric',
                              description: 'A headline value with a sparkline and period-over-period change.',
                              disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                          },
                      ]
                    : []),
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                    description: 'Proportions of a whole as a pie.',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconGraph className="rotate-90" />,
                    label: 'Bar chart',
                    description: 'Total values as horizontal bars.',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                    description: 'Total values in a table view.',
                },
            ],
        },
        {
            title: 'Visualizations',
            options: [
                {
                    value: ChartDisplayType.WorldMap,
                    icon: <IconGlobe />,
                    label: 'World map',
                    description: 'Values per country on a map.',
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
                ...(featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.CalendarHeatmap,
                              icon: <IconRetentionHeatmap />,
                              label: 'Calendar heatmap',
                              description: 'Values per day and hour.',
                          },
                      ]
                    : []),
            ],
        },
    ]

    const items = Object.fromEntries(
        groups.flatMap((group) =>
            group.options.map((option) => [
                option.value,
                <span className="flex items-center gap-2" key={option.value}>
                    {option.icon}
                    {option.label}
                </span>,
            ])
        )
    )

    return (
        <Select
            value={display || ChartDisplayType.ActionsLineGraph}
            items={items}
            onValueChange={(value: string | null) => {
                if (value) {
                    updateInsightFilter({ display: value as ChartDisplayType })
                }
            }}
            disabled={!!editingDisabledReason}
        >
            <SelectTrigger size="sm" data-quill data-attr="chart-filter" title={editingDisabledReason ?? undefined}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {groups.map((group) => (
                    <SelectGroup key={group.title}>
                        <SelectGroupLabel>{group.title}</SelectGroupLabel>
                        {group.options.map((option) => (
                            <SelectItem
                                key={option.value}
                                value={option.value}
                                disabled={!!option.disabledReason}
                                title={option.disabledReason}
                            >
                                {option.icon}
                                <span className="flex flex-col">
                                    <span>{option.label}</span>
                                    <span className="text-xs font-normal whitespace-normal text-muted-foreground">
                                        {option.description}
                                    </span>
                                </span>
                            </SelectItem>
                        ))}
                    </SelectGroup>
                ))}
            </SelectContent>
        </Select>
    )
}
