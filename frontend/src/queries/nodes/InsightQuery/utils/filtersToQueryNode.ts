import posthog from 'posthog-js'

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
    AnalyticsQueryResponseBase,
    BreakdownFilter,
    CompareFilter,
    DataWarehouseNode,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelPathsFilter,
    FunnelsFilter,
    FunnelsQuery,
    InsightNodeKind,
    InsightQueryNode,
    InsightsQueryBase,
    LifecycleFilter,
    MathType,
    NodeKind,
    PathsFilter,
    RetentionFilter,
    StickinessFilter,
    TrendsFilter,
} from '~/queries/schema/schema-general'
import {
    isFunnelsQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithCompare,
    isInsightQueryWithSeries,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    setLatestVersionsOnQuery,
} from '~/queries/utils'
import {
    ActionFilter,
    BaseMathType,
    CalendarHeatmapMathType,
    DataWarehouseFilter,
    FilterType,
    FunnelExclusionLegacy,
    FunnelMathType,
    FunnelsFilterType,
    GroupMathType,
    HogQLMathType,
    InsightType,
    PathsFilterType,
    RetentionEntity,
    RetentionFilterType,
    TrendsFilterType,
    isDataWarehouseFilter,
} from '~/types'

import { cleanEntityProperties, cleanGlobalProperties } from './cleanProperties'

const insightTypeToNodeKind: Record<
    Exclude<InsightType, InsightType.JSON | InsightType.SQL | InsightType.HOG>,
    InsightNodeKind
> = {
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

const funnelsMathTypes = [FunnelMathType.FirstTimeForUser, FunnelMathType.FirstTimeForUserWithFilters]

const calendarHeatmapMathTypes = [CalendarHeatmapMathType.TotalCount, CalendarHeatmapMathType.UniqueUsers]

export type FilterTypeActionsAndEvents = {
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
    }

    if (isDataWarehouseFilter(entity)) {
        shared = {
            ...shared,
            id_field: entity.id_field || undefined,
            timestamp_field: entity.timestamp_field || undefined,
            distinct_id_field: entity.distinct_id_field || undefined,
            table_name: entity.table_name || undefined,
        } as DataWarehouseNode
    }

    if (includeProperties) {
        shared = { ...shared, properties: cleanEntityProperties(entity.properties) } as any
    }

    if (mathAvailability !== MathAvailability.None) {
        // only trends, funnels, and stickiness insights support math.
        // transition to then default math for stickiness, when an unsupported math type is encountered.
        if (mathAvailability === MathAvailability.ActorsOnly && !actorsOnlyMathTypes.includes(entity.math as any)) {
            shared = {
                ...shared,
                math: BaseMathType.UniqueUsers,
            }
        } else if (mathAvailability === MathAvailability.FunnelsOnly) {
            if (funnelsMathTypes.includes(entity.math as any)) {
                shared = {
                    ...shared,
                    math: entity.math as MathType,
                }
            }
            if (entity.optionalInFunnel) {
                shared = {
                    ...shared,
                    optionalInFunnel: true,
                }
            }
        } else if (mathAvailability === MathAvailability.CalendarHeatmapOnly) {
            if (calendarHeatmapMathTypes.includes(entity.math as any)) {
                shared = {
                    ...shared,
                    math: entity.math as MathType,
                }
            }
        } else {
            shared = {
                ...shared,
                math: entity.math || 'total',
                math_property: entity.math_property,
                math_property_type: entity.math_property_type,
                math_hogql: entity.math_hogql,
                math_group_type_index: entity.math_group_type_index,
            } as any
        }
    }

    if (entity.type === 'actions') {
        return setLatestVersionsOnQuery(
            objectCleanWithEmpty({
                kind: NodeKind.ActionsNode,
                id: entity.id,
                ...shared,
            })
        ) as any
    } else if (entity.type === 'data_warehouse') {
        return setLatestVersionsOnQuery(
            objectCleanWithEmpty({
                kind: NodeKind.DataWarehouseNode,
                id: entity.id,
                ...shared,
            })
        ) as any
    }
    return setLatestVersionsOnQuery(
        objectCleanWithEmpty({
            kind: NodeKind.EventsNode,
            event: entity.id,
            ...shared,
        })
    ) as any
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

/**
 * Converts `hidden_legend_keys` in trends and stickiness insights to an array of hidden indexes.
 * Example: `{1: true, 2: false}` will become `[1]`.
 *
 * Note: `hidden_legend_keys` in funnel insights follow a different format.
 */
export const hiddenLegendKeysToIndexes = (
    hidden_legend_keys: Record<string, boolean | undefined> | undefined
): number[] | undefined => {
    return hidden_legend_keys
        ? Object.entries(hidden_legend_keys)
              .filter(([k, v]) => /^\d+$/.test(k) && v === true)
              .map(([k]) => Number(k))
        : undefined
}

/**
 * Converts `hidden_legend_keys` in funnel insights to an array of hidden breakdowns.
 * Example: `{Chrome: true, Firefox: false}` will become: `["Chrome"]`.
 *
 * Also handles pre-#12123 legacy format.
 * Example: {`events/$pageview/0/Baseline`: true} will become `['Baseline']`.
 *
 * Note: `hidden_legend_keys` in trends and stickiness insights follow a different format.
 */
export const hiddenLegendKeysToBreakdowns = (
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

const processBool = (value: string | boolean | null | undefined): boolean | undefined => {
    if (value == null) {
        return undefined
    } else if (typeof value === 'boolean') {
        return value
    } else if (typeof value == 'string') {
        return strToBool(value)
    }
    return false
}

const strToBool = (value: any): boolean | undefined => {
    if (value == null) {
        return undefined
    }
    return ['y', 'yes', 't', 'true', 'on', '1'].includes(String(value).toLowerCase())
}

export const filtersToQueryNode = (filters: Partial<FilterType>): InsightQueryNode => {
    const captureException = (message: string): void => {
        posthog.captureException(new Error(message), { filters, DataExploration: true })
    }

    if (!filters.insight) {
        throw new Error('filtersToQueryNode expects "insight"')
    }

    const query: InsightsQueryBase<AnalyticsQueryResponseBase> = {
        kind: insightTypeToNodeKind[filters.insight],
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
        explicitDate: processBool(filters.explicit_date),
    })

    // series + interval
    if (isInsightQueryWithSeries(query)) {
        let includeMath = MathAvailability.None
        const includeProperties = true
        if (isTrendsQuery(query)) {
            includeMath = MathAvailability.All
        } else if (isStickinessQuery(query)) {
            includeMath = MathAvailability.ActorsOnly
        } else if (isFunnelsQuery(query)) {
            includeMath = MathAvailability.FunnelsOnly
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
        // not undefined or null
        if (filters.breakdowns != null) {
            /* handle multi-breakdowns for funnels */
            if (isFunnelsFilter(filters)) {
                if (filters.breakdowns.length === 1) {
                    filters.breakdown_type = filters.breakdowns[0].type || 'event'
                    filters.breakdown = filters.breakdowns[0].property as string
                } else {
                    captureException(
                        'Could not convert multi-breakdown property `breakdowns` - found more than one breakdown'
                    )
                }
            }

            /* handle multi-breakdowns for trends */
            if (isTrendsFilter(filters)) {
                filters.breakdowns = filters.breakdowns.map((b) => ({
                    ...b,
                    // Compatibility with legacy funnel breakdowns when someone switches a view from funnels to trends
                    type: b.type || filters.breakdown_type || 'event',
                }))
            }
        } else if (
            /* handle missing breakdown_type */
            // check for undefined and null values
            filters.breakdown != null &&
            filters.breakdown_type == null
        ) {
            filters.breakdown_type = 'event'
        }

        query.breakdownFilter = breakdownFilterToQuery(filters, isTrendsFilter(filters))
    }

    // compare filter
    if (isInsightQueryWithCompare(query)) {
        query.compareFilter = compareFilterToQuery(filters)
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
        query.funnelPathsFilter = filtersToFunnelPathsQuery(filters)
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
        showAlertThresholdLines: filters.show_alert_threshold_lines,
        hiddenLegendIndexes: hiddenLegendKeysToIndexes(filters.hidden_legend_keys),
        aggregationAxisFormat: filters.aggregation_axis_format,
        aggregationAxisPrefix: filters.aggregation_axis_prefix,
        aggregationAxisPostfix: filters.aggregation_axis_postfix,
        decimalPlaces: filters.decimal_places,
        formula: filters.formula,
        display: filters.display,
        showValuesOnSeries: filters.show_values_on_series,
        showPercentStackView: filters.show_percent_stack_view,
        showLabelsOnSeries: filters.show_labels_on_series,
        yAxisScaleType: filters.y_axis_scale_type,
        showMultipleYAxes: filters.show_multiple_y_axes,
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
        hiddenLegendBreakdowns: hiddenLegendKeysToBreakdowns(filters.hidden_legend_keys),
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
        meanRetentionCalculation: filters.mean_retention_calculation || 'simple',
        cumulative: filters.cumulative,
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
        excludeEvents: filters.exclude_events,
        stepLimit: filters.step_limit,
        pathReplacements: filters.path_replacements,
        localPathCleaningFilters: filters.local_path_cleaning_filters,
        edgeLimit: filters.edge_limit,
        minEdgeWeight: filters.min_edge_weight,
        maxEdgeWeight: filters.max_edge_weight,
    })
}

export const filtersToFunnelPathsQuery = (filters: Partial<PathsFilterType>): FunnelPathsFilter | undefined => {
    if (filters.funnel_paths === undefined || filters.funnel_filter === undefined) {
        return undefined
    }

    return {
        funnelPathType: filters.funnel_paths,
        funnelSource: filtersToQueryNode(filters.funnel_filter) as FunnelsQuery,
        funnelStep: filters.funnel_filter?.funnel_step,
    }
}

export const stickinessFilterToQuery = (filters: Record<string, any>): StickinessFilter => {
    return objectCleanWithEmpty({
        display: filters.display,
        showLegend: filters.show_legend,
        hiddenLegendIndexes: hiddenLegendKeysToIndexes(filters.hidden_legend_keys),
        showValuesOnSeries: filters.show_values_on_series,
        computedAs: filters.computed_as,
    })
}

export const lifecycleFilterToQuery = (filters: Record<string, any>): LifecycleFilter => {
    return objectCleanWithEmpty({
        showLegend: filters.show_legend,
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
        breakdown_limit: filters.breakdown_limit,
        ...(isTrends
            ? {
                  breakdown_histogram_bin_count: filters.breakdown_histogram_bin_count,
                  breakdown_hide_other_aggregation: filters.breakdown_hide_other_aggregation,
              }
            : {}),
    })
}

export const compareFilterToQuery = (filters: Record<string, any>): CompareFilter => {
    return objectCleanWithEmpty({
        compare: filters.compare,
        compare_to: filters.compare_to,
    })
}
