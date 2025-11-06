import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectClean } from 'lib/utils'

import {
    ActionsNode,
    BreakdownFilter,
    CompareFilter,
    DataWarehouseNode,
    EventsNode,
    FunnelsFilterLegacy,
    InsightNodeKind,
    InsightQueryNode,
    LifecycleFilterLegacy,
    NodeKind,
    PathsFilterLegacy,
    RetentionFilterLegacy,
    StickinessFilterLegacy,
    TrendsFilterLegacy,
} from '~/queries/schema/schema-general'
import {
    isActionsNode,
    isDataWarehouseNode,
    isEventsNode,
    isFunnelsQuery,
    isLifecycleQuery,
    isPathsQuery,
    isPathsV2Query,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { ActionFilter, EntityTypes, FilterType, InsightType } from '~/types'

type FilterTypeActionsAndEvents = {
    events?: ActionFilter[]
    actions?: ActionFilter[]
    data_warehouse?: ActionFilter[]
    new_entity?: ActionFilter[]
}

export const seriesNodeToFilter = (
    node: EventsNode | ActionsNode | DataWarehouseNode,
    index?: number
): ActionFilter => {
    const entity: ActionFilter = objectClean({
        type: isDataWarehouseNode(node)
            ? EntityTypes.DATA_WAREHOUSE
            : isActionsNode(node)
              ? EntityTypes.ACTIONS
              : EntityTypes.EVENTS,
        id: isDataWarehouseNode(node) ? node.table_name : (!isActionsNode(node) ? node.event : node.id) || null,
        order: index,
        name: node.name,
        custom_name: node.custom_name,
        // TODO: math is not supported by funnel and lifecycle queries
        math: node.math,
        math_property: node.math_property,
        math_property_type: node.math_property_type as TaxonomicFilterGroupType,
        math_hogql: node.math_hogql,
        math_group_type_index: node.math_group_type_index,
        optionalInFunnel: node.optionalInFunnel,
        properties: node.properties as any, // TODO,
        ...(isDataWarehouseNode(node)
            ? {
                  table_name: node.table_name,
                  id_field: node.id_field,
                  timestamp_field: node.timestamp_field,
                  distinct_id_field: node.distinct_id_field,
              }
            : {}),
    })
    return entity
}

export const seriesToActionsAndEvents = (
    series: (EventsNode | ActionsNode | DataWarehouseNode)[]
): Required<FilterTypeActionsAndEvents> => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    const data_warehouse: ActionFilter[] = []
    const new_entity: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity = seriesNodeToFilter(node, index)
        if (isEventsNode(node)) {
            events.push(entity)
        } else if (isActionsNode(node)) {
            actions.push(entity)
        } else if (isDataWarehouseNode(node)) {
            data_warehouse.push(entity)
        } else {
            new_entity.push(entity)
        }
    })

    return { actions, events, data_warehouse, new_entity }
}

/**
 * Converts arrays of hidden items (`hiddenLegendIndexes` and `hiddenLegendBreakdowns`)
 * to their respective object variant for usage in `hidden_legend_keys`.
 *
 * Example: `["Chrome"]` will become `{Chrome: true}`.
 */
export const hiddenLegendItemsToKeys = (
    hidden_items: number[] | string[] | undefined
): Record<string, boolean | undefined> | undefined =>
    hidden_items?.reduce(
        (k, b) => {
            k[b] = true
            return k
        },
        {} as Record<string, boolean | undefined>
    )

export const nodeKindToInsightType: Record<InsightNodeKind, InsightType> = {
    [NodeKind.TrendsQuery]: InsightType.TRENDS,
    [NodeKind.FunnelsQuery]: InsightType.FUNNELS,
    [NodeKind.RetentionQuery]: InsightType.RETENTION,
    [NodeKind.PathsQuery]: InsightType.PATHS,
    [NodeKind.PathsV2Query]: InsightType.PATHS_V2,
    [NodeKind.StickinessQuery]: InsightType.STICKINESS,
    [NodeKind.LifecycleQuery]: InsightType.LIFECYCLE,
}

const nodeKindToFilterKey: Record<InsightNodeKind, string> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.PathsV2Query]: 'pathsV2Filter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export const queryNodeToFilter = (query: InsightQueryNode): Partial<FilterType> => {
    const filters: Partial<FilterType> = objectClean({
        insight: nodeKindToInsightType[query.kind],
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        date_to: query.dateRange?.date_to,
        // TODO: not used by retention queries
        date_from: query.dateRange?.date_from,
        explicit_date: query.dateRange?.explicitDate,
        entity_type: 'events',
        sampling_factor: query.samplingFactor,
    })

    if (!isRetentionQuery(query) && !isPathsQuery(query)) {
        const { actions, events, data_warehouse, new_entity } = seriesToActionsAndEvents(query.series)
        if (actions.length > 0) {
            filters.actions = actions
        }
        if (events.length > 0) {
            filters.events = events
        }
        if (data_warehouse.length > 0) {
            filters.data_warehouse = data_warehouse
        }
        if (new_entity.length > 0) {
            filters.new_entity = new_entity
        }
    }

    // TODO stickiness should probably support breakdowns as well
    if ((isTrendsQuery(query) || isFunnelsQuery(query)) && query.breakdownFilter) {
        Object.assign(filters, objectClean<Partial<Record<keyof BreakdownFilter, unknown>>>(query.breakdownFilter))
    }

    if ((isTrendsQuery(query) || isStickinessQuery(query)) && query.compareFilter) {
        Object.assign(filters, objectClean<Partial<Record<keyof CompareFilter, unknown>>>(query.compareFilter))
    }

    if (!isStickinessQuery(query)) {
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

    // we don't want to mutate the original query
    const queryCopy = JSON.parse(JSON.stringify(query))

    // replace camel cased props with the snake cased variant
    const camelCasedTrendsProps: TrendsFilterLegacy = {}
    const camelCasedFunnelsProps: FunnelsFilterLegacy = {}
    const camelCasedRetentionProps: RetentionFilterLegacy = {}
    const camelCasedPathsProps: PathsFilterLegacy = {}
    const camelCasedStickinessProps: StickinessFilterLegacy = {}
    const camelCasedLifecycleProps: LifecycleFilterLegacy = {}
    if (isTrendsQuery(queryCopy)) {
        camelCasedTrendsProps.hidden_legend_keys = hiddenLegendItemsToKeys(queryCopy.trendsFilter?.hiddenLegendIndexes)
        camelCasedTrendsProps.smoothing_intervals = queryCopy.trendsFilter?.smoothingIntervals
        camelCasedTrendsProps.decimal_places = queryCopy.trendsFilter?.decimalPlaces
        camelCasedTrendsProps.aggregation_axis_format = queryCopy.trendsFilter?.aggregationAxisFormat
        camelCasedTrendsProps.aggregation_axis_postfix = queryCopy.trendsFilter?.aggregationAxisPostfix
        camelCasedTrendsProps.aggregation_axis_prefix = queryCopy.trendsFilter?.aggregationAxisPrefix
        camelCasedTrendsProps.show_labels_on_series = queryCopy.trendsFilter?.showLabelsOnSeries
        camelCasedTrendsProps.show_percent_stack_view = queryCopy.trendsFilter?.showPercentStackView
        camelCasedTrendsProps.show_legend = queryCopy.trendsFilter?.showLegend
        camelCasedTrendsProps.show_values_on_series = queryCopy.trendsFilter?.showValuesOnSeries
        camelCasedTrendsProps.y_axis_scale_type = queryCopy.trendsFilter?.yAxisScaleType
        camelCasedTrendsProps.show_multiple_y_axes = queryCopy.trendsFilter?.showMultipleYAxes
        delete queryCopy.trendsFilter?.hiddenLegendIndexes
        delete queryCopy.trendsFilter?.smoothingIntervals
        delete queryCopy.trendsFilter?.decimalPlaces
        delete queryCopy.trendsFilter?.aggregationAxisFormat
        delete queryCopy.trendsFilter?.aggregationAxisPostfix
        delete queryCopy.trendsFilter?.aggregationAxisPrefix
        delete queryCopy.trendsFilter?.showLabelsOnSeries
        delete queryCopy.trendsFilter?.showPercentStackView
        delete queryCopy.trendsFilter?.showLegend
        delete queryCopy.trendsFilter?.showValuesOnSeries
        delete queryCopy.trendsFilter?.yAxisScaleType
        delete queryCopy.trendsFilter?.showMultipleYAxes
    } else if (isFunnelsQuery(queryCopy)) {
        camelCasedFunnelsProps.exclusions = queryCopy.funnelsFilter?.exclusions
            ? queryCopy.funnelsFilter.exclusions.map(({ funnelFromStep, funnelToStep, ...rest }, index) => ({
                  funnel_from_step: funnelFromStep,
                  funnel_to_step: funnelToStep,
                  order: index,
                  ...seriesNodeToFilter(rest),
              }))
            : undefined
        camelCasedFunnelsProps.bin_count = queryCopy.funnelsFilter?.binCount
        camelCasedFunnelsProps.breakdown_attribution_type = queryCopy.funnelsFilter?.breakdownAttributionType
        camelCasedFunnelsProps.breakdown_attribution_value = queryCopy.funnelsFilter?.breakdownAttributionValue
        camelCasedFunnelsProps.funnel_aggregate_by_hogql = queryCopy.funnelsFilter?.funnelAggregateByHogQL
        camelCasedFunnelsProps.funnel_to_step = queryCopy.funnelsFilter?.funnelToStep
        camelCasedFunnelsProps.funnel_from_step = queryCopy.funnelsFilter?.funnelFromStep
        camelCasedFunnelsProps.funnel_order_type = queryCopy.funnelsFilter?.funnelOrderType
        camelCasedFunnelsProps.funnel_viz_type = queryCopy.funnelsFilter?.funnelVizType
        camelCasedFunnelsProps.funnel_window_interval = queryCopy.funnelsFilter?.funnelWindowInterval
        camelCasedFunnelsProps.funnel_window_interval_unit = queryCopy.funnelsFilter?.funnelWindowIntervalUnit
        camelCasedFunnelsProps.hidden_legend_keys = hiddenLegendItemsToKeys(
            queryCopy.funnelsFilter?.hiddenLegendBreakdowns
        )
        camelCasedFunnelsProps.funnel_step_reference = queryCopy.funnelsFilter?.funnelStepReference
        delete queryCopy.funnelsFilter?.exclusions
        delete queryCopy.funnelsFilter?.binCount
        delete queryCopy.funnelsFilter?.breakdownAttributionType
        delete queryCopy.funnelsFilter?.breakdownAttributionValue
        delete queryCopy.funnelsFilter?.funnelAggregateByHogQL
        delete queryCopy.funnelsFilter?.funnelToStep
        delete queryCopy.funnelsFilter?.funnelFromStep
        delete queryCopy.funnelsFilter?.funnelOrderType
        delete queryCopy.funnelsFilter?.funnelVizType
        delete queryCopy.funnelsFilter?.funnelWindowInterval
        delete queryCopy.funnelsFilter?.funnelWindowIntervalUnit
        delete queryCopy.funnelsFilter?.hiddenLegendBreakdowns
        delete queryCopy.funnelsFilter?.funnelStepReference
    } else if (isRetentionQuery(queryCopy)) {
        camelCasedRetentionProps.retention_reference = queryCopy.retentionFilter?.retentionReference
        camelCasedRetentionProps.retention_type = queryCopy.retentionFilter?.retentionType
        camelCasedRetentionProps.returning_entity = queryCopy.retentionFilter?.returningEntity
        camelCasedRetentionProps.target_entity = queryCopy.retentionFilter?.targetEntity
        camelCasedRetentionProps.total_intervals = queryCopy.retentionFilter?.totalIntervals
        camelCasedRetentionProps.show_mean =
            queryCopy.retentionFilter?.meanRetentionCalculation === 'simple'
                ? true
                : queryCopy.retentionFilter?.meanRetentionCalculation === 'none'
                  ? false
                  : undefined
        camelCasedRetentionProps.cumulative = queryCopy.retentionFilter?.cumulative
        delete queryCopy.retentionFilter?.retentionReference
        delete queryCopy.retentionFilter?.retentionType
        delete queryCopy.retentionFilter?.returningEntity
        delete queryCopy.retentionFilter?.targetEntity
        delete queryCopy.retentionFilter?.totalIntervals
        delete queryCopy.retentionFilter?.cumulative
        delete queryCopy.retentionFilter?.meanRetentionCalculation
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
        camelCasedPathsProps.funnel_paths = queryCopy.funnelPathsFilter?.funnelPathType
        camelCasedPathsProps.funnel_filter =
            queryCopy.funnelPathsFilter !== undefined
                ? {
                      ...queryNodeToFilter(queryCopy.funnelPathsFilter.funnelSource),
                      funnel_step: queryCopy.funnelPathsFilter.funnelStep,
                  }
                : undefined
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
        delete queryCopy.funnelPathsFilter
    } else if (isStickinessQuery(queryCopy)) {
        camelCasedStickinessProps.show_legend = queryCopy.stickinessFilter?.showLegend
        camelCasedStickinessProps.show_values_on_series = queryCopy.stickinessFilter?.showValuesOnSeries
        camelCasedStickinessProps.hidden_legend_keys = hiddenLegendItemsToKeys(
            queryCopy.stickinessFilter?.hiddenLegendIndexes
        )
        delete queryCopy.stickinessFilter?.showLegend
        delete queryCopy.stickinessFilter?.showValuesOnSeries
        delete queryCopy.stickinessFilter?.hiddenLegendIndexes
    } else if (isLifecycleQuery(queryCopy)) {
        camelCasedLifecycleProps.show_values_on_series = queryCopy.lifecycleFilter?.showValuesOnSeries
        camelCasedLifecycleProps.show_legend = queryCopy.lifecycleFilter?.showLegend
        camelCasedLifecycleProps.toggledLifecycles = queryCopy.lifecycleFilter?.toggledLifecycles
        delete queryCopy.lifecycleFilter?.showLegend
        delete queryCopy.lifecycleFilter?.showValuesOnSeries
        delete queryCopy.lifecycleFilter?.toggledLifecycles
    }
    Object.assign(filters, camelCasedTrendsProps)
    Object.assign(filters, camelCasedFunnelsProps)
    Object.assign(filters, camelCasedRetentionProps)
    Object.assign(filters, camelCasedPathsProps)
    Object.assign(filters, camelCasedStickinessProps)
    Object.assign(filters, camelCasedLifecycleProps)

    // add the remaining node specific filter properties
    Object.assign(filters, queryCopy[nodeKindToFilterKey[query.kind]])

    return filters
}
