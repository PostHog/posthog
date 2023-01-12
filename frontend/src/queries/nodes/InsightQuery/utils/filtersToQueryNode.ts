import { InsightQueryNode, EventsNode, ActionsNode, NodeKind, SupportedNodeKind } from '~/queries/schema'
import { FilterType, InsightType, ActionFilter } from '~/types'
import { isLifecycleQuery, isStickinessQuery } from '~/queries/utils'
import { isLifecycleFilter, isStickinessFilter } from 'scenes/insights/sharedUtils'
import { objectClean } from 'lib/utils'

const reverseInsightMap: Record<InsightType, SupportedNodeKind> = {
    [InsightType.TRENDS]: NodeKind.TrendsQuery,
    [InsightType.FUNNELS]: NodeKind.FunnelsQuery,
    [InsightType.RETENTION]: NodeKind.RetentionQuery,
    [InsightType.PATHS]: NodeKind.PathsQuery,
    [InsightType.STICKINESS]: NodeKind.StickinessQuery,
    [InsightType.LIFECYCLE]: NodeKind.LifecycleQuery,
}

type FilterTypeActionsAndEvents = { events?: ActionFilter[]; actions?: ActionFilter[]; new_entity?: ActionFilter[] }

export const actionsAndEventsToSeries = ({
    actions,
    events,
    new_entity,
}: FilterTypeActionsAndEvents): (EventsNode | ActionsNode)[] => {
    const series: any = [...(actions || []), ...(events || []), ...(new_entity || [])]
        .sort((a, b) => (a.order || b.order ? (!a.order ? -1 : !b.order ? 1 : a.order - b.order) : 0))
        .map((f) => {
            const shared = {
                name: f.name || undefined,
                custom_name: f.custom_name,
                properties: f.properties,
                math: f.math,
                math_property: f.math_property,
                math_group_type_index: f.math_group_type_index,
            }
            if (f.type === 'actions') {
                return {
                    kind: NodeKind.ActionsNode,
                    id: f.id,
                    ...shared,
                }
            } else if (f.type === 'events') {
                return {
                    kind: NodeKind.EventsNode,
                    event: f.id,
                    ...shared,
                }
            } else if (f.type === 'new_entity') {
                return {
                    kind: NodeKind.NewEntityNode,
                    event: f.id,
                    ...shared,
                }
            }
        })

    return series
}

export const filtersToQueryNode = (filters: Partial<FilterType>): InsightQueryNode => {
    if (!filters.insight) {
        throw new Error('filtersToQueryNode expects "insight"')
    }

    const { events, actions } = filters
    const series = actionsAndEventsToSeries({ actions, events } as any)
    const query: InsightQueryNode = objectClean({
        kind: reverseInsightMap[filters.insight],
        properties: filters.properties,
        filterTestAccounts: filters.filter_test_accounts,
        dateRange: objectClean({
            date_to: filters.date_to,
            date_from: filters.date_from,
        }),
        breakdown: objectClean({
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
        query.lifecycleFilter = objectClean({
            shown_as: filters.shown_as,
        })
    }

    if (isStickinessFilter(filters) && isStickinessQuery(query)) {
        query.stickinessFilter = objectClean({
            display: filters.display,
        })
    }

    return query
}
