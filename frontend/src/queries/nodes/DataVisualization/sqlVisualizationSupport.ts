import { ChartDisplayType } from '~/types'

import { Column, applyVisualizationType } from './dataVisualizationLogic'

type VisualizationSupport = 'none' | 'axes' | 'manual'

const VISUALIZATION_SUPPORT: Record<ChartDisplayType, VisualizationSupport> = {
    [ChartDisplayType.Auto]: 'none',
    [ChartDisplayType.ActionsTable]: 'none',
    [ChartDisplayType.BoldNumber]: 'none',
    [ChartDisplayType.ActionsLineGraph]: 'axes',
    [ChartDisplayType.ActionsAreaGraph]: 'axes',
    [ChartDisplayType.ActionsBar]: 'axes',
    [ChartDisplayType.ActionsStackedBar]: 'axes',
    [ChartDisplayType.ActionsUnstackedBar]: 'axes',
    [ChartDisplayType.ActionsPie]: 'axes',
    [ChartDisplayType.ActionsDonut]: 'axes',
    [ChartDisplayType.ActionsLineGraphCumulative]: 'axes',
    [ChartDisplayType.ScatterPlot]: 'manual',
    [ChartDisplayType.TwoDimensionalHeatmap]: 'manual',
    [ChartDisplayType.ActionsBarValue]: 'manual',
    [ChartDisplayType.Metric]: 'manual',
    [ChartDisplayType.WorldMap]: 'manual',
    [ChartDisplayType.CalendarHeatmap]: 'manual',
    [ChartDisplayType.BoxPlot]: 'manual',
    [ChartDisplayType.SlopeGraph]: 'manual',
}

const MANUAL_SETUP_REASON = 'Open the insight to pick which column goes on each axis'

export function sqlVisualizationDisabledReason(
    displayType: ChartDisplayType,
    query: Parameters<typeof applyVisualizationType>[0],
    columns: Column[],
    rowCount: number,
    autoVisualizationType: ChartDisplayType
): string | undefined {
    const drawnAs = displayType === ChartDisplayType.Auto ? autoVisualizationType : displayType

    if (VISUALIZATION_SUPPORT[drawnAs] === 'manual') {
        return displayType === ChartDisplayType.Auto
            ? `Auto picks a chart here that needs its axes set. ${MANUAL_SETUP_REASON}.`
            : MANUAL_SETUP_REASON
    }

    if (VISUALIZATION_SUPPORT[drawnAs] !== 'axes') {
        return undefined
    }

    const nextQuery = applyVisualizationType(query, displayType, columns, rowCount)
    if (nextQuery.chartSettings?.xAxis && nextQuery.chartSettings.yAxis?.length) {
        return undefined
    }

    return nextQuery.chartSettings?.yAxis?.length
        ? 'This insight has no column left to label the X-axis'
        : 'This insight has no numeric column to plot'
}
