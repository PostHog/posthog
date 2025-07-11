import equal from 'fast-deep-equal'
import { getEventNamesForAction } from 'lib/utils'

import { examples } from '~/queries/examples'
import {
    DataTableNode,
    DataVisualizationNode,
    HogQuery,
    InsightNodeKind,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isInsightQueryWithSeries, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActionType,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightModel,
    InsightType,
    QueryBasedInsightModel,
} from '~/types'

import { nodeKindToDefaultQuery } from '../InsightQuery/defaults'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'

export const getAllEventNames = (query: InsightQueryNode, allActions: ActionType[]): string[] => {
    if (!isInsightQueryWithSeries(query)) {
        return []
    }

    const allEvents = query.series.flatMap((e) => {
        if (e.kind == NodeKind.EventsNode) {
            return e.event
        } else if (e.kind == NodeKind.ActionsNode) {
            return getEventNamesForAction(e.id, allActions)
        }
    })

    // has one "all events" event
    if (allEvents.some((e) => e === null)) {
        return []
    }

    // remove duplicates and empty events
    return Array.from(new Set(allEvents.filter((e): e is string => !!e)))
}

export const getCachedResults = (
    cachedInsight: Partial<QueryBasedInsightModel> | undefined | null,
    query: InsightQueryNode
): Partial<QueryBasedInsightModel> | undefined => {
    if (!cachedInsight) {
        return undefined
    }

    let cachedQueryNode: Node | undefined

    if (cachedInsight.query) {
        cachedQueryNode = cachedInsight.query
        if ('source' in cachedInsight.query) {
            cachedQueryNode = cachedInsight.query.source as Node
        }
    } else {
        return undefined
    }

    // only set the cached result when the filters match the currently set ones
    if (!equal(cachedQueryNode, query)) {
        return undefined
    }

    return cachedInsight
}

// these types exist so that the return type reflects the input model
// i.e. when given a partial model the return model is types as
// partial as well
type InputInsightModel = InsightModel | Partial<InsightModel>

type ReturnInsightModel<T> = T extends InsightModel
    ? QueryBasedInsightModel
    : T extends Partial<InsightModel>
    ? Partial<QueryBasedInsightModel>
    : never

/** Get an insight with `query` only. Eventual `filters` will be converted.  */
export function getQueryBasedInsightModel<T extends InputInsightModel>(insight: T): ReturnInsightModel<T> {
    const { filters, ...baseInsight } = insight
    return { ...baseInsight, query: getQueryFromInsightLike(insight) } as unknown as ReturnInsightModel<T>
}

/** Get a `query` from an object that potentially has `filters` instead of a `query`.  */
export function getQueryFromInsightLike(insight: {
    query?: Node<Record<string, any>> | null
    filters?: Partial<FilterType>
}): Node<Record<string, any>> | null {
    let query
    if (insight.query) {
        query = insight.query
    } else if (insight.filters && Object.keys(insight.filters).filter((k) => k != 'filter_test_accounts').length > 0) {
        query = { kind: NodeKind.InsightVizNode, source: filtersToQueryNode(insight.filters) } as InsightVizNode
    } else {
        query = null
    }

    return query
}

export const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind, filterTestAccountsDefault: boolean): InsightVizNode =>
    setLatestVersionsOnQuery({
        kind: NodeKind.InsightVizNode,
        source: { ...nodeKindToDefaultQuery[kind], ...(filterTestAccountsDefault ? { filterTestAccounts: true } : {}) },
    })

export const getDefaultQuery = (
    insightType: InsightType,
    filterTestAccountsDefault: boolean
): DataTableNode | DataVisualizationNode | HogQuery | InsightVizNode => {
    if ([InsightType.SQL, InsightType.JSON, InsightType.HOG].includes(insightType)) {
        if (insightType === InsightType.JSON) {
            return examples.TotalEventsTable as DataTableNode
        } else if (insightType === InsightType.SQL) {
            return examples.DataVisualization as DataVisualizationNode
        } else if (insightType === InsightType.HOG) {
            return examples.Hoggonacci as HogQuery
        }
    } else {
        if (insightType === InsightType.TRENDS) {
            return queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.FUNNELS) {
            return queryFromKind(NodeKind.FunnelsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.RETENTION) {
            return queryFromKind(NodeKind.RetentionQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.PATHS) {
            return queryFromKind(NodeKind.PathsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.STICKINESS) {
            return queryFromKind(NodeKind.StickinessQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.LIFECYCLE) {
            return queryFromKind(NodeKind.LifecycleQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.CALENDAR_HEATMAP) {
            return queryFromKind(NodeKind.CalendarHeatmapQuery, filterTestAccountsDefault)
        }
    }

    throw new Error('encountered unexpected type for view')
}

/** Get a dashboard where eventual `filters` based tiles are converted to `query` based ones. */
export const getQueryBasedDashboard = (
    dashboard: DashboardType<InsightModel> | null
): DashboardType<QueryBasedInsightModel> | null => {
    if (dashboard == null) {
        return null
    }

    return {
        ...dashboard,
        tiles: dashboard.tiles?.map(
            (tile) =>
                ({
                    ...tile,
                    ...(tile.insight != null ? { insight: getQueryBasedInsightModel(tile.insight) } : {}),
                } as DashboardTile<QueryBasedInsightModel>)
        ),
    }
}
