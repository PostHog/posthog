import {
    getDisplay,
    isDataTableNode,
    isDataVisualizationNode,
    isFunnelsQuery,
    isInsightVizNode,
    isPathsQuery,
    isRetentionQuery,
} from '~/queries/utils'
import { ChartDisplayType, FunnelVizType, InsightModel } from '~/types'

type VisualizationShape = 'line' | 'bar' | 'pie' | 'donut' | 'number' | 'table' | 'heatmap' | 'funnel'

const warnedDisplays = new Set<string>()

export function visualizationShape(query: InsightModel['query']): VisualizationShape {
    if (isDataTableNode(query)) {
        return 'table'
    }

    let display: ChartDisplayType | undefined
    if (isDataVisualizationNode(query)) {
        display = query.display ?? ChartDisplayType.ActionsTable
    } else if (isInsightVizNode(query)) {
        const source = query.source
        if (isRetentionQuery(source) || isPathsQuery(source)) {
            return 'table'
        }
        if (isFunnelsQuery(source)) {
            if (source.funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert) {
                return 'table'
            }
            return source.funnelsFilter?.funnelVizType === FunnelVizType.Trends ? 'line' : 'funnel'
        }
        display = getDisplay(source)
    }

    switch (display) {
        case ChartDisplayType.ActionsBar:
        case ChartDisplayType.ActionsUnstackedBar:
        case ChartDisplayType.ActionsStackedBar:
        case ChartDisplayType.ActionsBarValue:
        case ChartDisplayType.BoxPlot:
            return 'bar'
        case ChartDisplayType.ActionsPie:
            return 'pie'
        case ChartDisplayType.ActionsDonut:
            return 'donut'
        case ChartDisplayType.BoldNumber:
        case ChartDisplayType.Metric:
            return 'number'
        case ChartDisplayType.ActionsTable:
        case ChartDisplayType.Auto:
            return 'table'
        case ChartDisplayType.CalendarHeatmap:
        case ChartDisplayType.TwoDimensionalHeatmap:
        case ChartDisplayType.WorldMap:
            return 'heatmap'
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsAreaGraph:
        case ChartDisplayType.ActionsLineGraphCumulative:
        case ChartDisplayType.SlopeGraph:
        case ChartDisplayType.ScatterPlot:
            return 'line'
        default:
            display satisfies undefined
            if (display !== undefined && !warnedDisplays.has(display)) {
                warnedDisplays.add(display)
                console.warn('Unknown chart display type for visualization skeleton:', display)
            }
            return 'line'
    }
}
