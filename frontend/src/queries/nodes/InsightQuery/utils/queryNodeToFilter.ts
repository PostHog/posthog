import {
    InsightQueryNode,
    EventsNode,
    ActionsNode,
    SupportedNodeKind,
    NodeKind,
    BreakdownFilter,
} from '~/queries/schema'
import { FilterType, InsightType, ActionFilter, EntityTypes } from '~/types'
import {
    isEventsNode,
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isUnimplementedQuery,
    isLifecycleQuery,
} from '~/queries/utils'
import { objectClean } from 'lib/utils'

type FilterTypeActionsAndEvents = { events?: ActionFilter[]; actions?: ActionFilter[] }

const seriesToActionsAndEvents = (series: (EventsNode | ActionsNode)[]): Required<FilterTypeActionsAndEvents> => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity: ActionFilter = objectClean({
            type: isEventsNode(node) ? EntityTypes.EVENTS : EntityTypes.ACTIONS,
            id: (isEventsNode(node) ? node.event : node.id) || null,
            order: index,
            name: node.name,
            custom_name: node.custom_name,
            // TODO: math is not supported by funnel and lifecycle queries
            math: node.math,
            math_property: node.math_property,
            math_group_type_index: node.math_group_type_index,
            properties: node.properties as any, // TODO,
        })

        if (isEventsNode(node)) {
            events.push(entity)
        } else {
            actions.push(entity)
        }
    })
    if (actions.length + events.length === 1) {
        actions.length > 0 ? delete actions[0].order : delete events[0].order
    }

    return { actions, events }
}

const insightMap: Record<SupportedNodeKind, InsightType> = {
    [NodeKind.TrendsQuery]: InsightType.TRENDS,
    [NodeKind.FunnelsQuery]: InsightType.FUNNELS,
    [NodeKind.RetentionQuery]: InsightType.RETENTION,
    [NodeKind.PathsQuery]: InsightType.PATHS,
    [NodeKind.StickinessQuery]: InsightType.STICKINESS,
    [NodeKind.LifecycleQuery]: InsightType.LIFECYCLE,
}

const filterMap: Record<SupportedNodeKind, string> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export const queryNodeToFilter = (query: InsightQueryNode): Partial<FilterType> => {
    const filters: Partial<FilterType> = objectClean({
        insight: insightMap[query.kind],
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        date_to: query.dateRange?.date_to,
        // TODO: not used by retention queries
        date_from: query.dateRange?.date_from,
        entity_type: 'events',
    })

    if (!isRetentionQuery(query) && !isPathsQuery(query) && !isUnimplementedQuery(query)) {
        const { actions, events } = seriesToActionsAndEvents(query.series)
        if (actions.length > 0) {
            filters.actions = actions
        }
        if (events.length > 0) {
            filters.events = events
        }
    }

    // TODO stickiness should probably support breakdowns as well
    if ((isTrendsQuery(query) || isFunnelsQuery(query)) && query.breakdown) {
        Object.assign(filters, objectClean<Partial<Record<keyof BreakdownFilter, unknown>>>(query.breakdown))
    }

    if (isTrendsQuery(query) || isStickinessQuery(query) || isLifecycleQuery(query)) {
        filters.interval = query.interval
    }

    // get node specific filter properties e.g. trendsFilter, funnelsFilter, ...
    Object.assign(filters, query[filterMap[query.kind]])

    return filters
}
