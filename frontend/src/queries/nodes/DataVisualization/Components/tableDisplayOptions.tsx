import { IconGraph, IconLifecycle, IconPieChart, IconScatter, IconTrends } from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'

import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { Column } from '../types'

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
    [ChartDisplayType.ActionsBarValue]: 'Value chart',
    [ChartDisplayType.ActionsTable]: 'Table',
    [ChartDisplayType.WorldMap]: 'World map',
    [ChartDisplayType.CalendarHeatmap]: 'Calendar heatmap',
    [ChartDisplayType.TwoDimensionalHeatmap]: '2d heatmap',
    [ChartDisplayType.BoxPlot]: 'Box plot',
    [ChartDisplayType.SlopeGraph]: 'Slope graph',
    [ChartDisplayType.ScatterPlot]: 'Scatter plot',
}

// "Auto" resolves to a concrete type from the query's columns, so it reads as "Auto (Line chart)".
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
    /** Extra reason a surface cannot offer a type, checked before this list's own reasons. A surface
     * that can configure every type omits it. */
    disabledReasonFor?: (displayType: ChartDisplayType) => string | undefined
): LemonSelectOptions<ChartDisplayType> {
    const canDisplayContinuousChart = columns.length > 1 && numericalColumns.length > 0
    // Both scatter axes are numeric measures, so one numeric column can't fill both.
    const canDisplayScatterPlot = numericalColumns.length > 1

    return [
        {
            title: 'Auto',
            options: [
                {
                    value: ChartDisplayType.Auto,
                    icon: <IconTrends />,
                    label: renderDisplayTypeLabel(ChartDisplayType.Auto, autoVisualizationType),
                    disabledReason: disabledReasonFor?.(ChartDisplayType.Auto),
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
                    disabledReason: disabledReasonFor?.(ChartDisplayType.ActionsTable),
                },
                {
                    value: ChartDisplayType.BoldNumber,
                    icon: <Icon123 />,
                    label: 'Big number',
                    disabledReason: disabledReasonFor?.(ChartDisplayType.BoldNumber),
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
                    disabledReason:
                        disabledReasonFor?.(ChartDisplayType.ActionsLineGraph) ??
                        (!canDisplayContinuousChart
                            ? 'Requires at least two columns, including one numeric column'
                            : undefined),
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    disabledReason: disabledReasonFor?.(ChartDisplayType.ActionsBar),
                },
                {
                    value: ChartDisplayType.ActionsStackedBar,
                    icon: <IconLifecycle />,
                    label: 'Stacked bar chart',
                    disabledReason: disabledReasonFor?.(ChartDisplayType.ActionsStackedBar),
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    disabledReason:
                        disabledReasonFor?.(ChartDisplayType.ActionsAreaGraph) ??
                        (!canDisplayContinuousChart
                            ? 'Requires at least two columns, including one numeric column'
                            : undefined),
                },
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                    disabledReason: disabledReasonFor?.(ChartDisplayType.ActionsPie),
                },
                {
                    value: ChartDisplayType.ScatterPlot,
                    icon: <IconScatter />,
                    label: 'Scatter plot',
                    // The column requirement comes first: sending someone to the insight to pick axes
                    // does not help when the query has too few numeric columns to plot there either.
                    disabledReason: !canDisplayScatterPlot
                        ? 'Requires at least two numeric columns, one for each axis'
                        : disabledReasonFor?.(ChartDisplayType.ScatterPlot),
                },
                {
                    value: ChartDisplayType.TwoDimensionalHeatmap,
                    icon: <IconHeatmap />,
                    label: '2d heatmap',
                    disabledReason: disabledReasonFor?.(ChartDisplayType.TwoDimensionalHeatmap),
                },
            ],
        },
    ]
}
