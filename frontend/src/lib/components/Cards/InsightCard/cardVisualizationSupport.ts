import { deriveDefaultAxes } from '~/queries/nodes/DataVisualization/columnUtils'
import { Column } from '~/queries/nodes/DataVisualization/types'
import { DataVisualizationNode } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

// These plot columns against axes, so a card can only offer them when it can derive both.
export const AXIS_PLOTTING_TYPES = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsPie,
]

// These need columns assigned to named roles that no rule can guess, and a card has no control for
// assigning them.
const NEEDS_MANUAL_SETUP = [ChartDisplayType.ScatterPlot, ChartDisplayType.TwoDimensionalHeatmap]

const MANUAL_SETUP_REASON = 'Open the insight to pick which column goes on each axis'
const NO_PLOTTABLE_COLUMNS_REASON = 'This insight has no numeric column to plot'

export function resolveDisplayType(
    displayType: ChartDisplayType,
    autoVisualizationType: ChartDisplayType
): ChartDisplayType {
    return displayType === ChartDisplayType.Auto ? autoVisualizationType : displayType
}

// The one rule for what a dashboard card can switch a SQL insight to. Both the option list and the
// query it saves answer to this, so an offered type is always one the card can complete.
export function cardVisualizationDisabledReason(
    displayType: ChartDisplayType,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): string | undefined {
    const drawnAs = resolveDisplayType(displayType, autoVisualizationType)

    if (NEEDS_MANUAL_SETUP.includes(drawnAs)) {
        // Auto resolves from the columns, so the reason has to name that rather than the pick.
        return displayType === ChartDisplayType.Auto
            ? `This insight defaults to a ${drawnAs === ChartDisplayType.ScatterPlot ? 'scatter plot' : '2d heatmap'}. ${MANUAL_SETUP_REASON}`
            : MANUAL_SETUP_REASON
    }

    if (AXIS_PLOTTING_TYPES.includes(drawnAs)) {
        const { xAxis, yAxis } = deriveDefaultAxes(columns)
        if (!xAxis || yAxis.length === 0) {
            return NO_PLOTTABLE_COLUMNS_REASON
        }
    }

    return undefined
}

// A chart reads its columns out of chartSettings, and loading the saved query resets the axes to
// whatever it carries. So a query saved as a table has to gain axes here, or the chart draws empty.
export function withAxes(
    query: DataVisualizationNode,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): DataVisualizationNode {
    const drawnAs = query.display ? resolveDisplayType(query.display, autoVisualizationType) : undefined
    if (!drawnAs || !AXIS_PLOTTING_TYPES.includes(drawnAs)) {
        return query
    }

    const { xAxis, yAxis } = deriveDefaultAxes(columns)
    // Fill only the side the query is missing, so axes the user chose stay untouched.
    const nextXAxis = query.chartSettings?.xAxis ?? (xAxis ? { column: xAxis } : undefined)
    const nextYAxis = query.chartSettings?.yAxis?.length
        ? query.chartSettings.yAxis
        : yAxis.map((column) => ({ column }))

    if (!nextXAxis || nextYAxis.length === 0) {
        return query
    }

    return {
        ...query,
        chartSettings: { ...query.chartSettings, xAxis: nextXAxis, yAxis: nextYAxis },
    }
}
