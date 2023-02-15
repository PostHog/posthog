import {
    InsightQueryNode,
    EventsNode,
    ActionsNode,
    NodeKind,
    InsightNodeKind,
    InsightsQueryBase,
} from '~/queries/schema'
import { FilterType, InsightType, ActionFilter } from '~/types'
import {
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isLifecycleQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
} from '~/queries/utils'
import {
    isTrendsFilter,
    isFunnelsFilter,
    isRetentionFilter,
    isPathsFilter,
    isStickinessFilter,
    isLifecycleFilter,
} from 'scenes/insights/sharedUtils'
import { objectCleanWithEmpty } from 'lib/utils'

const reverseInsightMap: Record<Exclude<InsightType, InsightType.QUERY>, InsightNodeKind> = {
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
                properties: f.properties,
                math: f.math,
                math_property: f.math_property,
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

    const query: InsightsQueryBase = {
        kind: reverseInsightMap[filters.insight],
        properties: filters.properties,
        filterTestAccounts: filters.filter_test_accounts,
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
        query.breakdown = objectCleanWithEmpty({
            breakdown_type: filters.breakdown_type,
            breakdown: filters.breakdown,
            breakdown_normalize_url: filters.breakdown_normalize_url,
            breakdowns: filters.breakdowns,
            breakdown_value: filters.breakdown_value,
            breakdown_group_type_index: filters.breakdown_group_type_index,
            aggregation_group_type_index: filters.aggregation_group_type_index,
        })
    }

    // trends filter
    if (isTrendsFilter(filters) && isTrendsQuery(query)) {
        query.trendsFilter = objectCleanWithEmpty({
            smoothing_intervals: filters.smoothing_intervals,
            show_legend: filters.show_legend,
            hidden_legend_keys: filters.hidden_legend_keys,
            compare: filters.compare,
            aggregation_axis_format: filters.aggregation_axis_format,
            aggregation_axis_prefix: filters.aggregation_axis_prefix,
            aggregation_axis_postfix: filters.aggregation_axis_postfix,
            breakdown_histogram_bin_count: filters.breakdown_histogram_bin_count,
            formula: filters.formula,
            shown_as: filters.shown_as,
            display: filters.display,
        })
    }

    // funnels filter
    if (isFunnelsFilter(filters) && isFunnelsQuery(query)) {
        query.funnelsFilter = objectCleanWithEmpty({
            funnel_viz_type: filters.funnel_viz_type,
            funnel_from_step: filters.funnel_from_step,
            funnel_to_step: filters.funnel_to_step,
            funnel_step_reference: filters.funnel_step_reference,
            funnel_step_breakdown: filters.funnel_step_breakdown,
            breakdown_attribution_type: filters.breakdown_attribution_type,
            breakdown_attribution_value: filters.breakdown_attribution_value,
            bin_count: filters.bin_count,
            funnel_window_interval_unit: filters.funnel_window_interval_unit,
            funnel_window_interval: filters.funnel_window_interval,
            funnel_order_type: filters.funnel_order_type,
            exclusions: filters.exclusions,
            funnel_correlation_person_entity: filters.funnel_correlation_person_entity,
            funnel_correlation_person_converted: filters.funnel_correlation_person_converted,
            funnel_custom_steps: filters.funnel_custom_steps,
            funnel_advanced: filters.funnel_advanced,
            layout: filters.layout,
            funnel_step: filters.funnel_step,
            entrance_period_start: filters.entrance_period_start,
            drop_off: filters.drop_off,
            hidden_legend_keys: filters.hidden_legend_keys,
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
            include_event_types: filters.include_event_types,
            start_point: filters.start_point,
            end_point: filters.end_point,
            path_groupings: filters.path_groupings,
            funnel_paths: filters.funnel_paths,
            funnel_filter: filters.funnel_filter,
            exclude_events: filters.exclude_events,
            step_limit: filters.step_limit,
            path_start_key: filters.path_start_key,
            path_end_key: filters.path_end_key,
            path_dropoff_key: filters.path_dropoff_key,
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
            hidden_legend_keys: filters.hidden_legend_keys,
            stickiness_days: filters.stickiness_days,
            shown_as: filters.shown_as,
        })
    }

    // lifecycle filter
    if (isLifecycleFilter(filters) && isLifecycleQuery(query)) {
        query.lifecycleFilter = objectCleanWithEmpty({
            shown_as: filters.shown_as,
        })
    }

    // remove undefined and empty array/objects and return
    return objectCleanWithEmpty(query as Record<string, any>) as InsightQueryNode
}
