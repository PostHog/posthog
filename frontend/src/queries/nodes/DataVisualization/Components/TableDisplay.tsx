import { useActions, useValues } from 'kea'

import { IconGraph, IconLifecycle, IconPieChart, IconScatter, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ChartDisplayType } from '~/types'

import { Column, dataVisualizationLogic } from '../dataVisualizationLogic'

const DISPLAY_TYPE_LABELS: Record<ChartDisplayType, string> = {
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
    [ChartDisplayType.ActionsDonut]: 'Donut chart',
    [ChartDisplayType.ActionsBarValue]: 'Value chart',
    [ChartDisplayType.ActionsTable]: 'Table',
    [ChartDisplayType.WorldMap]: 'World map',
    [ChartDisplayType.CalendarHeatmap]: 'Calendar heatmap',
    [ChartDisplayType.TwoDimensionalHeatmap]: '2d heatmap',
    [ChartDisplayType.BoxPlot]: 'Box plot',
    [ChartDisplayType.SlopeGraph]: 'Slope graph',
    [ChartDisplayType.ScatterPlot]: 'Scatter plot',
}

export function renderDisplayTypeLabel(displayType: ChartDisplayType, autoVisualizationType: ChartDisplayType): string {
    const selectedLabel = DISPLAY_TYPE_LABELS[displayType] ?? displayType

    if (displayType !== ChartDisplayType.Auto) {
        return selectedLabel
    }

    const resolvedLabel = DISPLAY_TYPE_LABELS[autoVisualizationType] ?? autoVisualizationType
    return `Auto (${resolvedLabel})`
}

export function getTableDisplayOptions(
    columns: Column[],
    numericalColumns: Column[],
    autoVisualizationType: ChartDisplayType,
    disabledReasonFor?: (displayType: ChartDisplayType) => string | undefined,
    showBoxPlot = false
): LemonSelectOptions<ChartDisplayType> {
    const canDisplayContinuousChart = columns.length > 1 && numericalColumns.length > 0
    const canDisplayScatterPlot = numericalColumns.length > 1

    const groups: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Auto',
            options: [
                {
                    value: ChartDisplayType.Auto,
                    icon: <IconTrends />,
                    label: renderDisplayTypeLabel(ChartDisplayType.Auto, autoVisualizationType),
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
                    label: 'Big number',
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
                    value: ChartDisplayType.ScatterPlot,
                    icon: <IconScatter />,
                    label: 'Scatter plot',
                    disabledReason: !canDisplayScatterPlot
                        ? 'Requires at least two numeric columns, one for each axis'
                        : undefined,
                },
                ...(showBoxPlot
                    ? [
                          {
                              value: ChartDisplayType.BoxPlot,
                              icon: <IconGraph />,
                              label: 'Box plot',
                              disabledReason:
                                  numericalColumns.length < 6 ? 'Requires six numeric summary columns' : undefined,
                          },
                      ]
                    : []),
                {
                    value: ChartDisplayType.TwoDimensionalHeatmap,
                    icon: <IconHeatmap />,
                    label: '2d heatmap',
                },
            ],
        },
    ]

    if (!disabledReasonFor) {
        return groups
    }

    return groups.map((group) => ({
        ...group,
        options: group.options.map((option) =>
            'value' in option
                ? { ...option, disabledReason: option.disabledReason ?? disabledReasonFor(option.value) }
                : option
        ),
    }))
}

interface TableDisplayProps extends Pick<
    LemonSelectProps<ChartDisplayType>,
    'disabledReason' | 'fullWidth' | 'loading'
> {
    dataAttr?: string
    disabledReasonFor?: (displayType: ChartDisplayType) => string | undefined
}

export const TableDisplay = ({
    dataAttr = 'chart-filter',
    disabledReason,
    disabledReasonFor,
    fullWidth,
    loading,
}: TableDisplayProps): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { autoVisualizationType, columns, numericalColumns, visualizationType } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <LemonSelect
            disabledReason={disabledReason}
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-end"
            fullWidth={fullWidth}
            loading={loading}
            onChange={setVisualizationType}
            optionTooltipPlacement="left"
            options={getTableDisplayOptions(
                columns,
                numericalColumns,
                autoVisualizationType,
                disabledReasonFor,
                !!featureFlags[FEATURE_FLAGS.SQL_BOX_PLOT_INSIGHT]
            )}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            size="small"
            value={visualizationType}
            data-attr={dataAttr}
        />
    )
}
