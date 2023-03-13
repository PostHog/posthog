import {
    ActionsNode,
    BreakdownFilter,
    EventsNode,
    InsightNodeKind,
    InsightQueryNode,
    NewEntityNode,
    NodeKind,
} from '~/queries/schema'
import { ActionFilter, EntityTypes, FilterType, InsightType } from '~/types'
import {
    isActionsNode,
    isEventsNode,
    isFunnelsQuery,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { objectClean } from 'lib/utils'
import { isFunnelsFilter, isLifecycleFilter, isStickinessFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

type FilterTypeActionsAndEvents = { events?: ActionFilter[]; actions?: ActionFilter[]; new_entity?: ActionFilter[] }

export const seriesToActionsAndEvents = (
    series: (EventsNode | ActionsNode | NewEntityNode)[]
): Required<FilterTypeActionsAndEvents> => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    const new_entity: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity: ActionFilter = objectClean({
            type: isEventsNode(node)
                ? EntityTypes.EVENTS
                : isActionsNode(node)
                ? EntityTypes.ACTIONS
                : EntityTypes.NEW_ENTITY,
            id: (!isActionsNode(node) ? node.event : node.id) || null,
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
        } else if (isActionsNode(node)) {
            actions.push(entity)
        } else {
            new_entity.push(entity)
        }
    })

    if (actions.length + events.length + new_entity.length === 1) {
        actions.length > 0
            ? delete actions[0].order
            : events.length > 0
            ? delete events[0].order
            : delete new_entity[0].order
    }

    return { actions, events, new_entity }
}

export const hiddenLegendItemsToKeys = (
    hidden_items: number[] | string[] | undefined
): Record<string, boolean | undefined> | undefined =>
    // @ts-expect-error
    hidden_items?.reduce((k: Record<string, boolean | undefined>, b: string | number) => ({ ...k, [b]: true }), {})

export const insightMap: Record<InsightNodeKind, InsightType> = {
    [NodeKind.TrendsQuery]: InsightType.TRENDS,
    [NodeKind.FunnelsQuery]: InsightType.FUNNELS,
    [NodeKind.RetentionQuery]: InsightType.RETENTION,
    [NodeKind.PathsQuery]: InsightType.PATHS,
    [NodeKind.StickinessQuery]: InsightType.STICKINESS,
    [NodeKind.LifecycleQuery]: InsightType.LIFECYCLE,
}

const filterMap: Record<InsightNodeKind, string> = {
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

    if (!isRetentionQuery(query) && !isPathsQuery(query)) {
        const { actions, events, new_entity } = seriesToActionsAndEvents(query.series)
        if (actions.length > 0) {
            filters.actions = actions
        }
        if (events.length > 0) {
            filters.events = events
        }
        if (new_entity.length > 0) {
            filters.new_entity = new_entity
        }
    }

    // TODO stickiness should probably support breakdowns as well
    if ((isTrendsQuery(query) || isFunnelsQuery(query)) && query.breakdown) {
        Object.assign(filters, objectClean<Partial<Record<keyof BreakdownFilter, unknown>>>(query.breakdown))
    }

    if (isTrendsQuery(query) || isStickinessQuery(query) || isLifecycleQuery(query)) {
        filters.interval = query.interval
    }

    if (isTrendsQuery(query) && isTrendsFilter(filters)) {
        filters.display = query.trendsFilter?.display
        filters.hidden_legend_keys = hiddenLegendItemsToKeys(query.trendsFilter?.hidden_legend_indexes)
    }

    if (isStickinessQuery(query) && isStickinessFilter(filters)) {
        filters.display = query.stickinessFilter?.display
        filters.hidden_legend_keys = hiddenLegendItemsToKeys(query.stickinessFilter?.hidden_legend_indexes)
    }

    if (isFunnelsQuery(query) && isFunnelsFilter(filters)) {
        filters.hidden_legend_keys = hiddenLegendItemsToKeys(query.funnelsFilter?.hidden_legend_breakdowns)
    }

    if (isLifecycleQuery(query) && isLifecycleFilter(filters)) {
        filters.toggledLifecycles = query.lifecycleFilter?.toggledLifecycles
        filters.shown_as = query.lifecycleFilter?.shown_as
    }

    // get node specific filter properties e.g. trendsFilter, funnelsFilter, ...
    Object.assign(filters, query[filterMap[query.kind]])

    return filters
}
