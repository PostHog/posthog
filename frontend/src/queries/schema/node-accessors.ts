import { ChartDisplayType, FunnelVizType, IntervalType } from '~/types'

import {
    isActionsNode,
    isAnyDataWarehouseNode,
    isDataTableNode,
    isDataVisualizationNode,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightQueryWithBreakdown,
    isInsightQueryWithCompare,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isPathsQuery,
    isPersonsNode,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
} from './node-guards'
import {
    AnyDataWarehouseNode,
    AnyEntityNode,
    BreakdownFilter,
    CompareFilter,
    DateRange,
    GroupNode,
    InsightQueryNode,
    Node,
} from './schema-general'

export function dateRangeFor(node?: Node): DateRange | undefined {
    if (isInsightVizNode(node)) {
        return node.source.dateRange
    } else if (isInsightQueryNode(node)) {
        return node.dateRange
    } else if (isActionsNode(node)) {
        return undefined
    } else if (isEventsNode(node)) {
        return undefined
    } else if (isPersonsNode(node)) {
        return undefined
    } else if (isDataTableNode(node)) {
        return undefined
    }

    return undefined
}

export const getInterval = (query: InsightQueryNode): IntervalType | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.interval
    }
    if (isWebStatsTableQuery(query) || isWebOverviewQuery(query)) {
        return query.interval ?? 'day'
    }
    return undefined
}

// For trends/stickiness, ActionsStackedBar is a deprecated alias of ActionsBar (which renders stacked):
// the UI never emits it, but the API and MCP accept it. Normalizing here — the point all `display`
// selectors derive from — makes such insights behave exactly like their UI-created equivalents.
export const normalizeDisplay = (display: ChartDisplayType | undefined): ChartDisplayType | undefined =>
    display === ChartDisplayType.ActionsStackedBar ? ChartDisplayType.ActionsBar : display

export const getDisplay = (query: InsightQueryNode): ChartDisplayType | undefined => {
    if (isStickinessQuery(query)) {
        return normalizeDisplay(query.stickinessFilter?.display)
    } else if (isTrendsQuery(query)) {
        return normalizeDisplay(query.trendsFilter?.display)
    }
    return undefined
}

// Display types whose viz paints to a <canvas> (Chart.js / quill-charts), which repaints on every resize
// frame. Everything else renders as DOM/SVG and is cheap to keep mounted while a tile is resized.
const CANVAS_CHART_DISPLAY_TYPES = new Set<ChartDisplayType>([
    ChartDisplayType.Auto,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
    ChartDisplayType.ActionsProportionBar,
    ChartDisplayType.Metric,
    ChartDisplayType.BoxPlot,
    ChartDisplayType.SlopeGraph,
    ChartDisplayType.TwoDimensionalHeatmap,
    ChartDisplayType.ScatterPlot,
])

type QueryVizCanvasClassification = 'canvas' | 'non-canvas' | 'unknown'

function classifyQueryVizCanvas(query?: Node | null): QueryVizCanvasClassification {
    if (isDataTableNode(query)) {
        return 'non-canvas'
    }
    if (isDataVisualizationNode(query)) {
        if (!query.display) {
            return 'non-canvas'
        }
        if (query.display === ChartDisplayType.Auto) {
            return 'unknown'
        }
        return CANVAS_CHART_DISPLAY_TYPES.has(query.display) ? 'canvas' : 'non-canvas'
    }
    if (isInsightVizNode(query)) {
        const source = query.source
        if (isRetentionQuery(source) || isPathsQuery(source)) {
            return 'non-canvas'
        }
        if (isFunnelsQuery(source)) {
            // Steps (default) and Trends paint to canvas; Flow (Sankey) is SVG and TimeToConvert is a DOM table.
            const vizType = source.funnelsFilter?.funnelVizType
            return vizType !== FunnelVizType.Flow && vizType !== FunnelVizType.TimeToConvert ? 'canvas' : 'non-canvas'
        }
        return CANVAS_CHART_DISPLAY_TYPES.has(getDisplay(source) ?? ChartDisplayType.Auto) ? 'canvas' : 'non-canvas'
    }
    return 'unknown'
}

/**
 * Whether an insight's viz may paint to a <canvas>. Unknown visualizations count as canvas so resize throttling
 * remains conservative.
 */
export function queryVizRendersToCanvas(query?: Node | null): boolean {
    return classifyQueryVizCanvas(query) !== 'non-canvas'
}

/** Whether an insight's viz is definitely canvas-backed and safe to unmount when the page is hidden. */
export function queryVizDefinitelyRendersToCanvas(query?: Node | null): boolean {
    return classifyQueryVizCanvas(query) === 'canvas'
}

export const getFormula = (query: InsightQueryNode | null): string | undefined => {
    if (isTrendsQuery(query)) {
        return (
            query.trendsFilter?.formulaNodes?.[0]?.formula ||
            query.trendsFilter?.formulas?.[0] ||
            query.trendsFilter?.formula
        )
    }
    return undefined
}

export const getSeries = (query: InsightQueryNode): (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[] | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.series
    }
    return undefined
}

/** Client-side check: does this query have a data-warehouse-backed series (insight surface)?
 * For raw SQL / HogQL queries the client can't know without the backend — use
 * `dataWarehouseSourcesFromResponse` on the query response instead. */
export function queryUsesDataWarehouse(query?: Record<string, any> | null): boolean {
    if (!query) {
        return false
    }
    const source = isInsightVizNode(query) ? query.source : query
    if (isInsightQueryNode(source)) {
        return !!getSeries(source)?.some((entity) => isAnyDataWarehouseNode(entity))
    }
    return false
}

export const getBreakdown = (query: InsightQueryNode): BreakdownFilter | undefined => {
    if (isInsightQueryWithBreakdown(query)) {
        return query.breakdownFilter
    }
    return undefined
}

export const getCompareFilter = (query: InsightQueryNode): CompareFilter | undefined => {
    if (isInsightQueryWithCompare(query)) {
        return query.compareFilter
    }
    return undefined
}
