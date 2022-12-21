import { InsightQueryNode, EventsNode, ActionsNode, InsightNodeKind, NodeKind, BreakdownFilter } from '~/queries/schema'
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
import { isLifecycleFilter } from 'scenes/insights/sharedUtils'

type FilterTypeActionsAndEvents = { events?: ActionFilter[]; actions?: ActionFilter[] }

const seriesToActionsAndEvents = (series: (EventsNode | ActionsNode)[]): Required<FilterTypeActionsAndEvents> => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity: ActionFilter = filterUndefined({
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

export const actionsAndEventsToSeries = ({
    actions,
    events,
}: FilterTypeActionsAndEvents): (EventsNode | ActionsNode)[] => {
    const series: any = [...(actions || []), ...(events || [])]
        .sort((a, b) => (a.order || b.order ? (!a.order ? -1 : !b.order ? 1 : a.order - b.order) : 0))
        // TODO: handle new_entity type
        .map((f) =>
            f.type === 'actions'
                ? {
                      kind: NodeKind.ActionsNode,
                      id: f.id,
                      name: f.name || undefined,
                      custom_name: f.custom_name,
                      properties: f.properties,
                  }
                : {
                      kind: NodeKind.EventsNode,
                      event: f.id,
                      name: f.name || undefined,
                      custom_name: f.custom_name,
                      properties: f.properties,
                  }
        )

    return series
}

type SupportedNodeKind = Exclude<InsightNodeKind, NodeKind.UnimplementedQuery>

const insightMap: Record<SupportedNodeKind, InsightType> = {
    [NodeKind.TrendsQuery]: InsightType.TRENDS,
    [NodeKind.FunnelsQuery]: InsightType.FUNNELS,
    [NodeKind.RetentionQuery]: InsightType.RETENTION,
    [NodeKind.PathsQuery]: InsightType.PATHS,
    [NodeKind.StickinessQuery]: InsightType.STICKINESS,
    [NodeKind.LifecycleQuery]: InsightType.LIFECYCLE,
}
const reverseInsightMap: Record<InsightType, SupportedNodeKind> = {
    [InsightType.TRENDS]: NodeKind.TrendsQuery,
    [InsightType.FUNNELS]: NodeKind.FunnelsQuery,
    [InsightType.RETENTION]: NodeKind.RetentionQuery,
    [InsightType.PATHS]: NodeKind.PathsQuery,
    [InsightType.STICKINESS]: NodeKind.StickinessQuery,
    [InsightType.LIFECYCLE]: NodeKind.LifecycleQuery,
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
    const filters: Partial<FilterType> = filterUndefined({
        insight: insightMap[query.kind],
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        date_to: query.dateRange?.date_to,
        // TODO: not used by retention queries
        date_from: query.dateRange?.date_from,
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
        Object.assign(filters, filterUndefined<Partial<Record<keyof BreakdownFilter, unknown>>>(query.breakdown))
    }

    if (isTrendsQuery(query) || isStickinessQuery(query) || isLifecycleQuery(query)) {
        filters.interval = query.interval
    }

    // get node specific filter properties e.g. trendsFilter, funnelsFilter, ...
    Object.assign(filters, query[filterMap[query.kind]])

    return filters
}

export const filtersToQueryNode = (filters: Partial<FilterType>): InsightQueryNode => {
    if (!filters.insight) {
        throw new Error('filtersToQueryNode expects "insight"')
    }

    const { events, actions } = filters
    const series = actionsAndEventsToSeries({ actions, events } as any)
    const query: InsightQueryNode = filterUndefined({
        kind: reverseInsightMap[filters.insight],
        properties: filters.properties,
        filterTestAccounts: filters.filter_test_accounts,
        dateRange: filterUndefined({
            date_to: filters.date_to,
            date_from: filters.date_from,
        }),
        breakdown: filterUndefined({
            breakdown_type: filters.breakdown_type,
            breakdown: filters.breakdown,
            breakdown_normalize_url: filters.breakdown_normalize_url,
            breakdowns: filters.breakdowns,
            breakdown_value: filters.breakdown_value,
            breakdown_group_type_index: filters.breakdown_group_type_index,
            aggregation_group_type_index: filters.aggregation_group_type_index,
        }),
        interval: filters.interval,
        series,
    })

    if (isLifecycleFilter(filters) && isLifecycleQuery(query)) {
        query.lifecycleFilter = filterUndefined({
            shown_as: filters.shown_as,
        })
    }

    return query
}

function filterUndefined<T extends Record<string | number | symbol, unknown>>(object: T): T {
    const newObject = { ...object }
    Object.keys(newObject).forEach((k) => {
        if (newObject[k] === undefined) {
            delete newObject[k]
        }
    })
    return newObject
}
