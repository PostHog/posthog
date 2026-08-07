import { useActions, useValues } from 'kea'

import { IconGraph, IconLifecycle, IconPieChart, IconScatter, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableDisplayProps extends Pick<LemonSelectProps<ChartDisplayType>, 'disabledReason'> {}

export const TableDisplay = ({ disabledReason }: TableDisplayProps): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { autoVisualizationType, columns, numericalColumns, visualizationType } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const canDisplayContinuousChart = columns.length > 1 && numericalColumns.length > 0

    const displayTypeLabels: Record<ChartDisplayType, string> = {
        [ChartDisplayType.Auto]: 'Auto',
        [ChartDisplayType.ActionsLineGraph]: 'Line chart',
        [ChartDisplayType.ActionsBar]: 'Bar chart',
        [ChartDisplayType.ActionsUnstackedBar]: 'Unstacked bar chart',
        [ChartDisplayType.ActionsStackedBar]: 'Stacked bar chart',
        [ChartDisplayType.ActionsAreaGraph]: 'Area chart',
        [ChartDisplayType.ActionsLineGraphCumulative]: 'Cumulative line chart',
        [ChartDisplayType.BoldNumber]: 'Big number',
        [ChartDisplayType.Metric]: 'Metric',
        [ChartDisplayType.ActionsPie]: 'Pie chart',
        [ChartDisplayType.ActionsBarValue]: 'Value chart',
        [ChartDisplayType.ActionsTable]: 'Table',
        [ChartDisplayType.WorldMap]: 'World map',
        [ChartDisplayType.CalendarHeatmap]: 'Calendar heatmap',
        [ChartDisplayType.TwoDimensionalHeatmap]: '2d heatmap',
        [ChartDisplayType.BoxPlot]: 'Box plot',
        [ChartDisplayType.SlopeGraph]: 'Slope graph',
        [ChartDisplayType.ScatterPlot]: 'Scatter plot',
    }

    const renderDisplayTypeLabel = (displayType: ChartDisplayType): string => {
        const selectedLabel = displayTypeLabels[displayType] ?? displayType

        if (displayType !== ChartDisplayType.Auto) {
            return selectedLabel
        }

        const resolvedLabel = displayTypeLabels[autoVisualizationType] ?? autoVisualizationType
        return `Auto (${resolvedLabel})`
    }

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Auto',
            options: [
                {
                    value: ChartDisplayType.Auto,
                    icon: <IconTrends />,
                    label: renderDisplayTypeLabel(ChartDisplayType.Auto),
                },
            ],
        },
        {
            title: 'Table',
            options: [
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                },
                {
                    value: ChartDisplayType.BoldNumber,
                    icon: <Icon123 />,
                    label: 'Big Number',
                },
            ],
        },
        {
            title: 'Charts',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconTrends />,
                    label: 'Line chart',
                    disabledReason: !canDisplayContinuousChart
                        ? 'Requires at least two columns, including one numeric column'
                        : undefined,
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                },
                {
                    value: ChartDisplayType.ActionsStackedBar,
                    icon: <IconLifecycle />,
                    label: 'Stacked bar chart',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    disabledReason: !canDisplayContinuousChart
                        ? 'Requires at least two columns, including one numeric column'
                        : undefined,
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                },
                {
                    value: ChartDisplayType.TwoDimensionalHeatmap,
                    icon: <IconHeatmap />,
                    label: '2d heatmap',
                },
                ...(featureFlags[FEATURE_FLAGS.SCATTER_PLOT_INSIGHT]
                    ? [
                          {
                              value: ChartDisplayType.ScatterPlot,
                              icon: <IconScatter />,
                              label: 'Scatter plot',
                              disabledReason:
                                  numericalColumns.length < 2 ? 'Requires at least two numeric columns' : undefined,
                          },
                      ]
                    : []),
            ],
        },
    ]

    return (
        <LemonSelect
            disabledReason={disabledReason}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType)}
            onChange={(value) => {
                setVisualizationType(value)
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
