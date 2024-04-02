import * as Sentry from '@sentry/react'
import { objectCleanWithEmpty } from 'lib/utils'
import { transformLegacyHiddenLegendKeys } from 'scenes/funnels/funnelUtils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import {
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'

import {
    ActionsNode,
    BreakdownFilter,
    DataWarehouseNode,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsFilter,
    InsightNodeKind,
    InsightQueryNode,
    InsightsQueryBase,
    LifecycleFilter,
    NodeKind,
    PathsFilter,
    RetentionFilter,
    StickinessFilter,
    TrendsFilter,
} from '~/queries/schema'
import {
    isFunnelsQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import {
    ActionFilter,
    BaseMathType,
    DataWarehouseFilter,
    FilterType,
    FunnelExclusionLegacy,
    FunnelsFilterType,
    GroupMathType,
    HogQLMathType,
    InsightType,
    isDataWarehouseFilter,
    PathsFilterType,
    RetentionEntity,
    RetentionFilterType,
    TrendsFilterType,
} from '~/types'

import { cleanEntityProperties, cleanGlobalProperties } from './cleanProperties'

const reverseInsightMap: Record<Exclude<InsightType, InsightType.JSON | InsightType.SQL>, InsightNodeKind> = {
    [InsightType.TRENDS]: NodeKind.TrendsQuery,
    [InsightType.FUNNELS]: NodeKind.FunnelsQuery,
    [InsightType.RETENTION]: NodeKind.RetentionQuery,
    [InsightType.PATHS]: NodeKind.PathsQuery,
    [InsightType.STICKINESS]: NodeKind.StickinessQuery,
    [InsightType.LIFECYCLE]: NodeKind.LifecycleQuery,
}

const actorsOnlyMathTypes = [
    BaseMathType.UniqueUsers,
    BaseMathType.WeeklyActiveUsers,
    BaseMathType.MonthlyActiveUsers,
    GroupMathType.UniqueGroup,
    HogQLMathType.HogQL,
]

type FilterTypeActionsAndEvents = {
    events?: ActionFilter[]
    actions?: ActionFilter[]
    data_warehouse?: DataWarehouseFilter[]
    new_entity?: ActionFilter[]
}

export const legacyEntityToNode = (
    entity: ActionFilter | DataWarehouseFilter,
    includeProperties: boolean,
    mathAvailability: MathAvailability
): EventsNode | ActionsNode | DataWarehouseNode => {
    let shared: Partial<EventsNode | ActionsNode | DataWarehouseNode> = {
        name: entity.name || undefined,
        custom_name: entity.custom_name || undefined,
        id_field: 'id_field' in entity ? entity.id_field : undefined,
        timestamp_field: 'timestamp_field' in entity ? entity.timestamp_field : undefined,
        distinct_id_field: 'distinct_id_field' in entity ? entity.distinct_id_field : undefined,
        table_name: 'table_name' in entity ? entity.table_name : undefined,
    }

    if (isDataWarehouseFilter(entity)) {
        shared = {
            ...shared,
            id_field: entity.id_field || undefined,
            timestamp_field: entity.timestamp_field || undefined,
            distinct_id_field: entity.distinct_id_field || undefined,
            table_name: entity.table_name || undefined,
        }
    }

    if (includeProperties) {
        shared = { ...shared, properties: cleanEntityProperties(entity.properties) } as any
    }

    if (mathAvailability !== MathAvailability.None) {
        // only trends and stickiness insights support math.
        // transition to then default math for stickiness, when an unsupported math type is encountered.
        if (mathAvailability === MathAvailability.ActorsOnly && !actorsOnlyMathTypes.includes(entity.math as any)) {
            shared = {
                ...shared,
                math: BaseMathType.UniqueUsers,
            }
        } else {
            shared = {
                ...shared,
                math: entity.math || 'total',
                math_property: entity.math_property,
                math_hogql: entity.math_hogql,
                math_group_type_index: entity.math_group_type_index,
            } as any
        }
    }

    if (entity.type === 'actions') {
        return objectCleanWithEmpty({
            kind: NodeKind.ActionsNode,
            id: entity.id,
            ...shared,
        }) as any
    } else if (entity.type === 'data_warehouse') {
        return objectCleanWithEmpty({
            kind: NodeKind.DataWarehouseNode,
            id: entity.id,
            ...shared,
        }) as any
    } else {
        return objectCleanWithEmpty({
            kind: NodeKind.EventsNode,
            event: entity.id,
            ...shared,
        }) as any
    }
}

export const exlusionEntityToNode = (
    entity: FunnelExclusionLegacy
): FunnelExclusionEventsNode | FunnelExclusionActionsNode => {
    const baseEntity = legacyEntityToNode(entity as ActionFilter, false, MathAvailability.None) as
        | EventsNode
        | ActionsNode
    return {
        ...baseEntity,
        funnelFromStep: entity.funnel_from_step,
        funnelToStep: entity.funnel_to_step,
    }
}

export const actionsAndEventsToSeries = (
    { actions, events, data_warehouse, new_entity }: FilterTypeActionsAndEvents,
    includeProperties: boolean,
    includeMath: MathAvailability
): (EventsNode | ActionsNode | DataWarehouseNode)[] => {
    const series: any = [...(actions || []), ...(events || []), ...(data_warehouse || []), ...(new_entity || [])]
        .sort((a, b) => (a.order || b.order ? (!a.order ? -1 : !b.order ? 1 : a.order - b.order) : 0))
        .map((f) => legacyEntityToNode(f, includeProperties, includeMath))

    return series
}

export const cleanHiddenLegendIndexes = (
    hidden_legend_keys: Record<string, boolean | undefined> | undefined
): number[] | undefined => {
    return hidden_legend_keys
        ? Object.entries(hidden_legend_keys)
              .filter(([k, v]) => /^\d+$/.test(k) && v === true)
              .map(([k]) => Number(k))
        : undefined
}

export const cleanHiddenLegendSeries = (
    hidden_legend_keys: Record<string, boolean | undefined> | undefined
): string[] | undefined => {
    return hidden_legend_keys
        ? Object.entries(transformLegacyHiddenLegendKeys(hidden_legend_keys))
              .filter(([k, v]) => !/^\d+$/.test(k) && v === true)
              .map(([k]) => k)
        : undefined
}
export const sanitizeRetentionEntity = (entity: RetentionEntity | undefined): RetentionEntity | undefined => {
    if (!entity) {
        return undefined
    }
    const record = { ...entity }
    for (const key of Object.keys(record)) {
        if (!['id', 'kind', 'name', 'type', 'order', 'uuid', 'custom_name'].includes(key)) {
            delete record[key]
        }
    }
    if ('id' in record && record.type === 'actions') {
        record.id = Number(record.id)
    }
    return record
}

export const filtersToQueryNode = (filters: Partial<FilterType>): InsightQueryNode => {
    const captureException = (message: string): void => {
        Sentry.captureException(new Error(message), {
            tags: { DataExploration: true },
            extra: { filters },
        })
    }

    if (!filters.insight) {
        throw new Error('filtersToQueryNode expects "insight"')
    }

    const query: InsightsQueryBase = {
        kind: reverseInsightMap[filters.insight],
        properties: cleanGlobalProperties(filters.properties),
        filterTestAccounts: filters.filter_test_accounts,
    }
    if (filters.sampling_factor) {
        query.samplingFactor = filters.sampling_factor
    }

    // date range
    query.dateRange = objectCleanWithEmpty({
        date_to: filters.date_to,
        date_from: filters.date_from,
    })

    // series + interval
    if (isInsightQueryWithSeries(query)) {
        let includeMath = MathAvailability.None
        const includeProperties = true
        if (isTrendsQuery(query)) {
            includeMath = MathAvailability.All
        } else if (isStickinessQuery(query)) {
            includeMath = MathAvailability.ActorsOnly
        }

        const { events, actions, data_warehouse } = filters
        query.series = actionsAndEventsToSeries(
            { actions, events, data_warehouse } as any,
            includeProperties,
            includeMath
        )
        query.interval = filters.interval
    }

    // breakdown
    if (isInsightQueryWithBreakdown(query)) {
        /* handle multi-breakdowns */
        // not undefined or null
        if (filters.breakdowns != null) {
            if (filters.breakdowns.length === 1) {
                filters.breakdown_type = filters.breakdowns[0].type
                filters.breakdown = filters.breakdowns[0].property as string
            } else {
                captureException(
                    'Could not convert multi-breakdown property `breakdowns` - found more than one breakdown'
                )
            }
        }

        /* handle missing breakdown_type */
        // check for undefined and null values
        if (filters.breakdown != null && filters.breakdown_type == null) {
            filters.breakdown_type = 'event'
        }

        query.breakdownFilter = breakdownFilterToQuery(filters, isTrendsFilter(filters))
    }

    // group aggregation
    if (filters.aggregation_group_type_index !== undefined) {
        query.aggregation_group_type_index = filters.aggregation_group_type_index
    }

    // trends filter
    if (isTrendsFilter(filters) && isTrendsQuery(query)) {
        query.trendsFilter = trendsFilterToQuery(filters)
    }

    // funnels filter
    if (isFunnelsFilter(filters) && isFunnelsQuery(query)) {
        query.funnelsFilter = funnelsFilterToQuery(filters)
    }

    // retention filter
    if (isRetentionFilter(filters) && isRetentionQuery(query)) {
        query.retentionFilter = retentionFilterToQuery(filters)
    }

    // paths filter
    if (isPathsFilter(filters) && isPathsQuery(query)) {
        query.pathsFilter = pathsFilterToQuery(filters)
    }

    // stickiness filter
    if (isStickinessFilter(filters) && isStickinessQuery(query)) {
        query.stickinessFilter = stickinessFilterToQuery(filters)
    }

    // lifecycle filter
    if (isLifecycleFilter(filters) && isLifecycleQuery(query)) {
        query.lifecycleFilter = lifecycleFilterToQuery(filters)
    }

    // remove undefined and empty array/objects and return
    return objectCleanWithEmpty(query as Record<string, any>, ['series']) as InsightQueryNode
}

export const trendsFilterToQuery = (filters: Partial<TrendsFilterType>): TrendsFilter => {
    return objectCleanWithEmpty({
        smoothingIntervals: filters.smoothing_intervals,
        showLegend: filters.show_legend,
        hidden_legend_indexes: cleanHiddenLegendIndexes(filters.hidden_legend_keys),
        compare: filters.compare,
        aggregationAxisFormat: filters.aggregation_axis_format,
        aggregationAxisPrefix: filters.aggregation_axis_prefix,
        aggregationAxisPostfix: filters.aggregation_axis_postfix,
        decimalPlaces: filters.decimal_places,
        formula: filters.formula,
        display: filters.display,
        showValuesOnSeries: filters.show_values_on_series,
        showPercentStackView: filters.show_percent_stack_view,
        showLabelsOnSeries: filters.show_labels_on_series,
    })
}

export const funnelsFilterToQuery = (filters: Partial<FunnelsFilterType>): FunnelsFilter => {
    return objectCleanWithEmpty({
        funnelVizType: filters.funnel_viz_type,
        funnelFromStep: filters.funnel_from_step,
        funnelToStep: filters.funnel_to_step,
        funnelStepReference: filters.funnel_step_reference,
        breakdownAttributionType: filters.breakdown_attribution_type,
        breakdownAttributionValue: filters.breakdown_attribution_value,
        binCount: filters.bin_count,
        funnelWindowIntervalUnit: filters.funnel_window_interval_unit,
        funnelWindowInterval: filters.funnel_window_interval,
        funnelOrderType: filters.funnel_order_type,
        exclusions:
            filters.exclusions !== undefined
                ? filters.exclusions.map((entity) => exlusionEntityToNode(entity))
                : undefined,
        layout: filters.layout,
        hidden_legend_breakdowns: cleanHiddenLegendSeries(filters.hidden_legend_keys),
        funnelAggregateByHogQL: filters.funnel_aggregate_by_hogql,
    })
}

export const retentionFilterToQuery = (filters: Partial<RetentionFilterType>): RetentionFilter => {
    return objectCleanWithEmpty({
        retentionType: filters.retention_type,
        retentionReference: filters.retention_reference,
        totalIntervals: filters.total_intervals,
        returningEntity: sanitizeRetentionEntity(filters.returning_entity),
        targetEntity: sanitizeRetentionEntity(filters.target_entity),
        period: filters.period,
    })
    // TODO: query.aggregation_group_type_index
}

export const pathsFilterToQuery = (filters: Partial<PathsFilterType>): PathsFilter => {
    return objectCleanWithEmpty({
        pathsHogQLExpression: filters.paths_hogql_expression,
        includeEventTypes: filters.include_event_types,
        startPoint: filters.start_point,
        endPoint: filters.end_point,
        pathGroupings: filters.path_groupings,
        funnelPaths: filters.funnel_paths,
        funnelFilter: filters.funnel_filter,
        excludeEvents: filters.exclude_events,
        stepLimit: filters.step_limit,
        pathReplacements: filters.path_replacements,
        localPathCleaningFilters: filters.local_path_cleaning_filters,
        edgeLimit: filters.edge_limit,
        minEdgeWeight: filters.min_edge_weight,
        maxEdgeWeight: filters.max_edge_weight,
    })
}

export const stickinessFilterToQuery = (filters: Record<string, any>): StickinessFilter => {
    return objectCleanWithEmpty({
        display: filters.display,
        compare: filters.compare,
        showLegend: filters.show_legend,
        hidden_legend_indexes: cleanHiddenLegendIndexes(filters.hidden_legend_keys),
        showValuesOnSeries: filters.show_values_on_series,
    })
}

export const lifecycleFilterToQuery = (filters: Record<string, any>): LifecycleFilter => {
    return objectCleanWithEmpty({
        toggledLifecycles: filters.toggledLifecycles,
        showValuesOnSeries: filters.show_values_on_series,
    })
}

export const breakdownFilterToQuery = (filters: Record<string, any>, isTrends: boolean): BreakdownFilter => {
    return objectCleanWithEmpty({
        breakdown_type: filters.breakdown_type,
        breakdown: filters.breakdown,
        breakdown_normalize_url: filters.breakdown_normalize_url,
        breakdowns: filters.breakdowns,
        breakdown_group_type_index: filters.breakdown_group_type_index,
        ...(isTrends
            ? {
                  breakdown_histogram_bin_count: filters.breakdown_histogram_bin_count,
                  breakdown_hide_other_aggregation: filters.breakdown_hide_other_aggregation,
              }
            : {}),
    })
}
