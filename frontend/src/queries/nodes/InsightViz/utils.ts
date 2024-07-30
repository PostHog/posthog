import equal from 'fast-deep-equal'
import { getEventNamesForAction, isEmptyObject } from 'lib/utils'

import { InsightQueryNode, InsightVizNode, Node, NodeKind } from '~/queries/schema'
import { isInsightQueryWithSeries } from '~/queries/utils'
import { ActionType, DashboardTile, DashboardType, FilterType, InsightModel, QueryBasedInsightModel } from '~/types'

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
    cachedInsight: Partial<InsightModel> | undefined | null,
    query: InsightQueryNode
): Partial<InsightModel> | undefined => {
    if (!cachedInsight) {
        return undefined
    }

    let cachedQueryNode: Node | undefined

    if (cachedInsight.query) {
        cachedQueryNode = cachedInsight.query
        if ('source' in cachedInsight.query) {
            cachedQueryNode = cachedInsight.query.source as Node
        }
    } else if (cachedInsight.filters && !isEmptyObject(cachedInsight.filters)) {
        cachedQueryNode = filtersToQueryNode(cachedInsight.filters)
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

/** Get a dashboard where eventual `filters` based tiles are converted to `query` based ones. */
export const getQueryBasedDashboard = (
    dashboard: DashboardType<InsightModel> | null
): DashboardType<QueryBasedInsightModel> | null => {
    if (dashboard == null) {
        return null
    }

    return {
        ...dashboard,
        tiles: dashboard.tiles.map(
            (tile) =>
                ({
                    ...tile,
                    insight: tile.insight != null ? getQueryBasedInsightModel(tile.insight) : null,
                } as DashboardTile<QueryBasedInsightModel>)
        ),
    }
}
