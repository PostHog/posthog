import * as Sentry from '@sentry/react'
import { objectCleanWithEmpty } from 'lib/utils'
import { transformLegacyHiddenLegendKeys } from 'scenes/funnels/funnelUtils'
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
    EventsNode,
    InsightNodeKind,
    InsightQueryNode,
    InsightsQueryBase,
    NodeKind,
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
    AnyPropertyFilter,
    FilterLogicalOperator,
    FilterType,
    InsightType,
    PropertyFilterType,
    PropertyGroupFilterValue,
    PropertyOperator,
} from '~/types'

const reverseInsightMap: Record<Exclude<InsightType, InsightType.JSON | InsightType.SQL>, InsightNodeKind> = {
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
            const shared = objectCleanWithEmpty({
                name: f.name || undefined,
                custom_name: f.custom_name,
                properties: cleanProperties(f.properties),
                math: f.math || 'total',
                math_property: f.math_property,
                math_hogql: f.math_hogql,
                math_group_type_index: f.math_group_type_index,
            })
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
            }
        })

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

const cleanProperties = (parentProperties: FilterType['properties']): InsightsQueryBase['properties'] => {
    if (!parentProperties || !parentProperties.values) {
        return parentProperties
    }

    const processAnyPropertyFilter = (filter: AnyPropertyFilter): AnyPropertyFilter => {
        if (
            filter.type === PropertyFilterType.Event ||
            filter.type === PropertyFilterType.Person ||
            filter.type === PropertyFilterType.Element ||
            filter.type === PropertyFilterType.Session ||
            filter.type === PropertyFilterType.Group ||
            filter.type === PropertyFilterType.Feature ||
            filter.type === PropertyFilterType.Recording
        ) {
            return {
                ...filter,
                operator: filter.operator ?? PropertyOperator.Exact,
            }
        }

        return filter
    }

    const processPropertyGroupFilterValue = (
        propertyGroupFilterValue: PropertyGroupFilterValue
    ): PropertyGroupFilterValue => {
        if (propertyGroupFilterValue.values?.length === 0 || !propertyGroupFilterValue.values) {
            return propertyGroupFilterValue
        }

        // Check whether the first values type is an AND or OR
        const firstValueType = propertyGroupFilterValue.values[0].type

        if (firstValueType === FilterLogicalOperator.And || firstValueType === FilterLogicalOperator.Or) {
            // propertyGroupFilterValue.values is PropertyGroupFilterValue[]
            const values = (propertyGroupFilterValue.values as PropertyGroupFilterValue[]).map(
                processPropertyGroupFilterValue
            )

            return {
                ...propertyGroupFilterValue,
                values,
            }
        }

        // propertyGroupFilterValue.values is AnyPropertyFilter[]
        const values = (propertyGroupFilterValue.values as AnyPropertyFilter[]).map(processAnyPropertyFilter)

        return {
            ...propertyGroupFilterValue,
            values,
        }
    }

    if (Array.isArray(parentProperties)) {
        // parentProperties is AnyPropertyFilter[]
        return parentProperties.map(processAnyPropertyFilter)
    }

    // parentProperties is PropertyGroupFilter
    const values = parentProperties.values.map(processPropertyGroupFilterValue)
    return {
        ...parentProperties,
        values,
    }
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
        properties: cleanProperties(filters.properties),
        filterTestAccounts: filters.filter_test_accounts,
        samplingFactor: filters.sampling_factor,
    }

    // date range
    query.dateRange = objectCleanWithEmpty({
        date_to: filters.date_to,
        date_from: filters.date_from,
    })

    // series + interval
    if (isInsightQueryWithSeries(query)) {
        const { events, actions } = filters
        const series = actionsAndEventsToSeries({ actions, events } as any)
        query.series = series
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

        query.breakdown = objectCleanWithEmpty({
            breakdown_type: filters.breakdown_type,
            breakdown: filters.breakdown,
            breakdown_normalize_url: filters.breakdown_normalize_url,
            breakdowns: filters.breakdowns,
            breakdown_group_type_index: filters.breakdown_group_type_index,
            ...(isTrendsFilter(filters)
                ? {
                      breakdown_histogram_bin_count: filters.breakdown_histogram_bin_count,
                      breakdown_hide_other_aggregation: filters.breakdown_hide_other_aggregation,
                  }
                : {}),
        })
    }

    // group aggregation
    if (filters.aggregation_group_type_index !== undefined) {
        query.aggregation_group_type_index = filters.aggregation_group_type_index
    }

    // trends filter
    if (isTrendsFilter(filters) && isTrendsQuery(query)) {
        query.trendsFilter = objectCleanWithEmpty({
            smoothing_intervals: filters.smoothing_intervals,
            show_legend: filters.show_legend,
            hidden_legend_indexes: cleanHiddenLegendIndexes(filters.hidden_legend_keys),
            compare: filters.compare,
            aggregation_axis_format: filters.aggregation_axis_format,
            aggregation_axis_prefix: filters.aggregation_axis_prefix,
            aggregation_axis_postfix: filters.aggregation_axis_postfix,
            decimal_places: filters.decimal_places,
            formula: filters.formula,
            display: filters.display,
            show_values_on_series: filters.show_values_on_series,
            show_percent_stack_view: filters.show_percent_stack_view,
        })
    }

    // funnels filter
    if (isFunnelsFilter(filters) && isFunnelsQuery(query)) {
        query.funnelsFilter = objectCleanWithEmpty({
            funnel_viz_type: filters.funnel_viz_type,
            funnel_from_step: filters.funnel_from_step,
            funnel_to_step: filters.funnel_to_step,
            funnel_step_reference: filters.funnel_step_reference,
            breakdown_attribution_type: filters.breakdown_attribution_type,
            breakdown_attribution_value: filters.breakdown_attribution_value,
            bin_count: filters.bin_count,
            funnel_window_interval_unit: filters.funnel_window_interval_unit,
            funnel_window_interval: filters.funnel_window_interval,
            funnel_order_type: filters.funnel_order_type,
            exclusions: filters.exclusions,
            layout: filters.layout,
            hidden_legend_breakdowns: cleanHiddenLegendSeries(filters.hidden_legend_keys),
            funnel_aggregate_by_hogql: filters.funnel_aggregate_by_hogql,
        })
    }

    // retention filter
    if (isRetentionFilter(filters) && isRetentionQuery(query)) {
        query.retentionFilter = objectCleanWithEmpty({
            retention_type: filters.retention_type,
            retention_reference: filters.retention_reference,
            total_intervals: filters.total_intervals,
            returning_entity: filters.returning_entity,
            target_entity: filters.target_entity,
            period: filters.period,
        })
        // TODO: query.aggregation_group_type_index
    }

    // paths filter
    if (isPathsFilter(filters) && isPathsQuery(query)) {
        query.pathsFilter = objectCleanWithEmpty({
            path_type: filters.path_type,
            paths_hogql_expression: filters.paths_hogql_expression,
            include_event_types: filters.include_event_types,
            start_point: filters.start_point,
            end_point: filters.end_point,
            path_groupings: filters.path_groupings,
            funnel_paths: filters.funnel_paths,
            funnel_filter: filters.funnel_filter,
            exclude_events: filters.exclude_events,
            step_limit: filters.step_limit,
            path_replacements: filters.path_replacements,
            local_path_cleaning_filters: filters.local_path_cleaning_filters,
            edge_limit: filters.edge_limit,
            min_edge_weight: filters.min_edge_weight,
            max_edge_weight: filters.max_edge_weight,
        })
    }

    // stickiness filter
    if (isStickinessFilter(filters) && isStickinessQuery(query)) {
        query.stickinessFilter = objectCleanWithEmpty({
            display: filters.display,
            compare: filters.compare,
            show_legend: filters.show_legend,
            hidden_legend_indexes: cleanHiddenLegendIndexes(filters.hidden_legend_keys),
            show_values_on_series: filters.show_values_on_series,
        })
    }

    // lifecycle filter
    if (isLifecycleFilter(filters) && isLifecycleQuery(query)) {
        query.lifecycleFilter = objectCleanWithEmpty({
            toggledLifecycles: filters.toggledLifecycles,
            show_values_on_series: filters.show_values_on_series,
        })
    }

    // remove undefined and empty array/objects and return
    return objectCleanWithEmpty(query as Record<string, any>, ['series']) as InsightQueryNode
}
