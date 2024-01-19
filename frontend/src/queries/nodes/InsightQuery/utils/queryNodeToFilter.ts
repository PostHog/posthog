import { objectClean } from 'lib/utils'
import { isFunnelsFilter, isLifecycleFilter, isStickinessFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

import {
    ActionsNode,
    BreakdownFilter,
    EventsNode,
    InsightNodeKind,
    InsightQueryNode,
    LifecycleFilterLegacy,
    NodeKind,
    PathsFilterLegacy,
    RetentionFilterLegacy,
    StickinessFilterLegacy,
    TrendsFilterLegacy,
} from '~/queries/schema'
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
import { ActionFilter, EntityTypes, FilterType, InsightType } from '~/types'

type FilterTypeActionsAndEvents = { events?: ActionFilter[]; actions?: ActionFilter[]; new_entity?: ActionFilter[] }

export const seriesNodeToFilter = (node: EventsNode | ActionsNode, index?: number): ActionFilter => {
    const entity: ActionFilter = objectClean({
        type: isActionsNode(node) ? EntityTypes.ACTIONS : EntityTypes.EVENTS,
        id: (!isActionsNode(node) ? node.event : node.id) || null,
        order: index,
        name: node.name,
        custom_name: node.custom_name,
        // TODO: math is not supported by funnel and lifecycle queries
        math: node.math,
        math_property: node.math_property,
        math_hogql: node.math_hogql,
        math_group_type_index: node.math_group_type_index,
        properties: node.properties as any, // TODO,
    })
    return entity
}

export const seriesToActionsAndEvents = (
    series: (EventsNode | ActionsNode)[]
): Required<FilterTypeActionsAndEvents> => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    const new_entity: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity = seriesNodeToFilter(node, index)
        if (isEventsNode(node)) {
            events.push(entity)
        } else if (isActionsNode(node)) {
            actions.push(entity)
        } else {
            new_entity.push(entity)
        }
    })

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
        sampling_factor: query.samplingFactor,
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
    if ((isTrendsQuery(query) || isFunnelsQuery(query)) && query.breakdownFilter) {
        Object.assign(filters, objectClean<Partial<Record<keyof BreakdownFilter, unknown>>>(query.breakdownFilter))
    }

    if (!isLifecycleQuery(query) && !isStickinessQuery(query)) {
        Object.assign(
            filters,
            objectClean({
                aggregation_group_type_index: query.aggregation_group_type_index,
            })
        )
    }

    if (isTrendsQuery(query) || isStickinessQuery(query) || isLifecycleQuery(query) || isFunnelsQuery(query)) {
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
    }

    // we don't want to mutate the original query
    const queryCopy = JSON.parse(JSON.stringify(query))

    // replace camel cased props with the snake cased variant
    const camelCasedTrendsProps: TrendsFilterLegacy = {}
    const camelCasedRetentionProps: RetentionFilterLegacy = {}
    const camelCasedPathsProps: PathsFilterLegacy = {}
    const camelCasedStickinessProps: StickinessFilterLegacy = {}
    const camelCasedLifecycleProps: LifecycleFilterLegacy = {}
    if (isTrendsQuery(queryCopy)) {
        camelCasedTrendsProps.smoothing_intervals = queryCopy.trendsFilter?.smoothingIntervals
        camelCasedTrendsProps.decimal_places = queryCopy.trendsFilter?.decimalPlaces
        camelCasedTrendsProps.aggregation_axis_format = queryCopy.trendsFilter?.aggregationAxisFormat
        camelCasedTrendsProps.aggregation_axis_postfix = queryCopy.trendsFilter?.aggregationAxisPostfix
        camelCasedTrendsProps.aggregation_axis_prefix = queryCopy.trendsFilter?.aggregationAxisPrefix
        camelCasedTrendsProps.show_labels_on_series = queryCopy.trendsFilter?.showLabelsOnSeries
        camelCasedTrendsProps.show_percent_stack_view = queryCopy.trendsFilter?.showPercentStackView
        camelCasedTrendsProps.show_legend = queryCopy.trendsFilter?.showLegend
        camelCasedTrendsProps.show_values_on_series = queryCopy.trendsFilter?.showValuesOnSeries
        delete queryCopy.trendsFilter?.smoothingIntervals
        delete queryCopy.trendsFilter?.decimalPlaces
        delete queryCopy.trendsFilter?.aggregationAxisFormat
        delete queryCopy.trendsFilter?.aggregationAxisPostfix
        delete queryCopy.trendsFilter?.aggregationAxisPrefix
        delete queryCopy.trendsFilter?.showLabelsOnSeries
        delete queryCopy.trendsFilter?.showPercentStackView
        delete queryCopy.trendsFilter?.showLegend
        delete queryCopy.trendsFilter?.showValuesOnSeries
    } else if (isRetentionQuery(queryCopy)) {
        camelCasedRetentionProps.retention_reference = queryCopy.retentionFilter?.retentionReference
        camelCasedRetentionProps.retention_type = queryCopy.retentionFilter?.retentionType
        camelCasedRetentionProps.returning_entity = queryCopy.retentionFilter?.returningEntity
        camelCasedRetentionProps.target_entity = queryCopy.retentionFilter?.targetEntity
        camelCasedRetentionProps.total_intervals = queryCopy.retentionFilter?.totalIntervals
        delete queryCopy.retentionFilter?.retentionReference
        delete queryCopy.retentionFilter?.retentionType
        delete queryCopy.retentionFilter?.returningEntity
        delete queryCopy.retentionFilter?.targetEntity
        delete queryCopy.retentionFilter?.totalIntervals
    } else if (isPathsQuery(queryCopy)) {
        camelCasedPathsProps.edge_limit = queryCopy.pathsFilter?.edgeLimit
        camelCasedPathsProps.paths_hogql_expression = queryCopy.pathsFilter?.pathsHogQLExpression
        camelCasedPathsProps.include_event_types = queryCopy.pathsFilter?.includeEventTypes
        camelCasedPathsProps.start_point = queryCopy.pathsFilter?.startPoint
        camelCasedPathsProps.end_point = queryCopy.pathsFilter?.endPoint
        camelCasedPathsProps.path_groupings = queryCopy.pathsFilter?.pathGroupings
        camelCasedPathsProps.exclude_events = queryCopy.pathsFilter?.excludeEvents
        camelCasedPathsProps.step_limit = queryCopy.pathsFilter?.stepLimit
        camelCasedPathsProps.path_replacements = queryCopy.pathsFilter?.pathReplacements
        camelCasedPathsProps.local_path_cleaning_filters = queryCopy.pathsFilter?.localPathCleaningFilters
        camelCasedPathsProps.min_edge_weight = queryCopy.pathsFilter?.minEdgeWeight
        camelCasedPathsProps.max_edge_weight = queryCopy.pathsFilter?.maxEdgeWeight
        camelCasedPathsProps.funnel_paths = queryCopy.pathsFilter?.funnelPaths
        camelCasedPathsProps.funnel_filter = queryCopy.pathsFilter?.funnelFilter
        delete queryCopy.pathsFilter?.edgeLimit
        delete queryCopy.pathsFilter?.pathsHogQLExpression
        delete queryCopy.pathsFilter?.includeEventTypes
        delete queryCopy.pathsFilter?.startPoint
        delete queryCopy.pathsFilter?.endPoint
        delete queryCopy.pathsFilter?.pathGroupings
        delete queryCopy.pathsFilter?.excludeEvents
        delete queryCopy.pathsFilter?.stepLimit
        delete queryCopy.pathsFilter?.pathReplacements
        delete queryCopy.pathsFilter?.localPathCleaningFilters
        delete queryCopy.pathsFilter?.minEdgeWeight
        delete queryCopy.pathsFilter?.maxEdgeWeight
        delete queryCopy.pathsFilter?.funnelPaths
        delete queryCopy.pathsFilter?.funnelFilter
    } else if (isStickinessQuery(queryCopy)) {
        camelCasedStickinessProps.show_legend = queryCopy.stickinessFilter?.showLegend
        camelCasedStickinessProps.show_values_on_series = queryCopy.stickinessFilter?.showValuesOnSeries
        delete queryCopy.stickinessFilter?.showLegend
        delete queryCopy.stickinessFilter?.showValuesOnSeries
    } else if (isLifecycleQuery(queryCopy)) {
        camelCasedLifecycleProps.show_values_on_series = queryCopy.lifecycleFilter?.showValuesOnSeries
        delete queryCopy.lifecycleFilter?.showValuesOnSeries
    }
    Object.assign(filters, camelCasedTrendsProps)
    Object.assign(filters, camelCasedRetentionProps)
    Object.assign(filters, camelCasedPathsProps)
    Object.assign(filters, camelCasedStickinessProps)
    Object.assign(filters, camelCasedLifecycleProps)

    // add the remaining node specific filter properties
    Object.assign(filters, queryCopy[filterMap[query.kind]])

    return filters
}
