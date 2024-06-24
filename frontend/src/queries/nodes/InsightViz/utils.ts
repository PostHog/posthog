import equal from 'fast-deep-equal'
import { getEventNamesForAction, isEmptyObject } from 'lib/utils'

import { InsightQueryNode, InsightVizNode, Node, NodeKind, TrendsQuery } from '~/queries/schema'
import { ActionType, FilterType, InsightModel, QueryBasedInsightModel } from '~/types'

import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '../InsightQuery/utils/queryNodeToFilter'

export const getAllEventNames = (query: InsightQueryNode, allActions: ActionType[]): string[] => {
    const { actions, events } = seriesToActionsAndEvents((query as TrendsQuery).series || [])

    // If there's a "All events" entity, don't filter by event names.
    if (events.find((e) => e.id === null)) {
        return []
    }

    const allEvents = [
        ...events.map((e) => String(e.id)),
        ...actions.flatMap((action) => getEventNamesForAction(action.id as string | number, allActions)),
    ]

    // remove duplicates and empty events
    return Array.from(new Set(allEvents.filter((a): a is string => !!a)))
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
