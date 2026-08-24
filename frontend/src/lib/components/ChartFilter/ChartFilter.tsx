import { useActions, useValues } from 'kea'

import { IconGlobe, IconGraph, IconPieChart, IconRetentionHeatmap, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart, IconCumulativeChart, IconTableChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

interface ChartFilterProps {
    /** Set on surfaces that stack their controls in a column, such as a dashboard card's menu. */
    fullWidth?: boolean
    className?: string
    /** Dashboard filters make an insight refuse edits, because what is on screen is not what is
     * saved. A surface that saves nothing derived from the filtered result can opt out. */
    allowEditingWithOverrides?: boolean
    /** Extra reason a surface cannot offer a type, checked before this list's own reasons. */
    disabledReasonFor?: (displayType: ChartDisplayType) => string | undefined
    /** Defaults to the editor's value. Override it so a surface can be told apart in analytics. */
    dataAttr?: string
}

export function ChartFilter({
    fullWidth,
    className,
    allowEditingWithOverrides,
    disabledReasonFor,
    dataAttr = 'chart-filter',
}: ChartFilterProps = {}): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const { isTrends, isSingleSeriesOutput, formula, breakdownFilter } = useValues(insightVizDataLogic(insightProps))

    const trendsOnlyDisabledReason = !isTrends ? 'This type is only available in Trends.' : undefined
    const singleSeriesOnlyDisabledReason = !isSingleSeriesOutput
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
                    value: ChartDisplayType.ActionsUnstackedBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    labelInMenu: (
                        <ChartFilterOptionLabel
                            label="Bar chart"
                            description="Trends over time as vertical bars side-by-side."
                        />
                    ),
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Stacked bar chart',
                    labelInMenu: (
                        <ChartFilterOptionLabel
                            label="Stacked bar chart"
                            description="Trends over time as vertical bars."
                        />
                    ),
                },
                ...(featureFlags[FEATURE_FLAGS.BOX_PLOT_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.BoxPlot,
                              icon: <IconGraph />,
                              label: 'Box plot',
                              disabledReason: trendsOnlyDisabledReason,
                              labelInMenu: (
                                  <ChartFilterOptionLabel
                                      label="Box plot"
                                      description="Distribution of a property over time showing quartiles."
                                  />
                              ),
                          },
                      ]
                    : []),
                ...(featureFlags[FEATURE_FLAGS.SLOPE_GRAPH_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.SlopeGraph,
                              icon: <IconTrends />,
                              label: 'Slope graph',
                              disabledReason: trendsOnlyDisabledReason,
                              labelInMenu: (
                                  <ChartFilterOptionLabel
                                      label="Slope graph"
                                      description="Change from the start to the end of the range, one line per series."
                                  />
                              ),
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
                ...(featureFlags[FEATURE_FLAGS.METRIC_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.Metric,
                              icon: <IconTrends />,
                              label: 'Metric',
                              labelInMenu: (
                                  <ChartFilterOptionLabel
                                      label="Metric"
                                      description="A headline value with a sparkline and period-over-period change."
                                  />
                              ),
                              disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                          },
                      ]
                    : []),
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
            ],
        },
        {
            title: 'Visualizations',
            options: [
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
                {
                    value: ChartDisplayType.CalendarHeatmap,
                    icon: <IconRetentionHeatmap />,
                    label: 'Calendar heatmap',
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                    labelInMenu: (
                        <ChartFilterOptionLabel label="Calendar heatmap" description="Values per day and hour." />
                    ),
                },
            ],
        },
    ]

    const withSurfaceReason = options.map((group) => ({
        ...group,
        options: group.options.map((option) =>
            'value' in option
                ? { ...option, disabledReason: disabledReasonFor?.(option.value) ?? option.disabledReason }
                : option
        ),
    }))

    return (
        <LemonSelect
            key="2"
            fullWidth={fullWidth}
            className={className}
            value={display || ChartDisplayType.ActionsLineGraph}
            onChange={(value) => {
                updateInsightFilter({ display: value })
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr={dataAttr}
            options={withSurfaceReason}
            size="small"
            disabledReason={allowEditingWithOverrides ? undefined : editingDisabledReason}
        />
    )
}
