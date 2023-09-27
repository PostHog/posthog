import {
    AnyFilterType,
    ChartDisplayType,
    Entity,
    EntityTypes,
    FilterType,
    FunnelsFilterType,
    FunnelVizType,
    InsightType,
    LifecycleFilterType,
    PathsFilterType,
    PathType,
    RetentionFilterType,
    RetentionPeriod,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'
import { deepCleanFunnelExclusionEvents, getClampedStepRangeFilter, isStepsUndefined } from 'scenes/funnels/funnelUtils'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import {
    BIN_COUNT_AUTO,
    NON_VALUES_ON_SERIES_DISPLAY_TYPES,
    PERCENT_STACK_VIEW_DISPLAY_TYPE,
    RETENTION_FIRST_TIME,
    ShownAsValue,
} from 'lib/constants'
import { autocorrectInterval } from 'lib/utils'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsDataLogic'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { LocalFilter, toLocalFilters } from '../filters/ActionFilter/entityFilterLogic'
import {
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { isURLNormalizeable } from 'scenes/insights/filters/BreakdownFilter/taxonomicBreakdownFilterUtils'

export function getDefaultEvent(): Entity {
    const event = getDefaultEventName()
    return {
        id: event,
        name: event,
        type: EntityTypes.EVENTS,
        order: 0,
    }
}

/** Take the first series from filters and, based on it, apply the most relevant breakdown type to cleanedParams. */
const useMostRelevantBreakdownType = (cleanedParams: Partial<FilterType>, filters: Partial<FilterType>): void => {
    const series: LocalFilter | undefined = toLocalFilters(filters)[0]
    cleanedParams['breakdown_type'] = ['dau', 'weekly_active', 'monthly_active'].includes(series?.math || '')
        ? 'person'
        : 'event'
}

function cleanBreakdownNormalizeURL(
    breakdown: string,
    breakdownNormalizeURL: boolean | undefined
): boolean | undefined {
    return isURLNormalizeable(breakdown)
        ? breakdownNormalizeURL !== undefined
            ? breakdownNormalizeURL
            : true
        : undefined
}

const cleanBreakdownParams = (cleanedParams: Partial<FilterType>, filters: Partial<FilterType>): void => {
    const isStepsFunnel = isFunnelsFilter(filters) && filters.funnel_viz_type === FunnelVizType.Steps
    const isTrends = isTrendsFilter(filters)
    const canBreakdown = isStepsFunnel || isTrends

    const canMultiPropertyBreakdown = isStepsFunnel

    cleanedParams['breakdowns'] = undefined
    cleanedParams['breakdown'] = undefined
    cleanedParams['breakdown_type'] = undefined
    cleanedParams['breakdown_group_type_index'] = undefined
    cleanedParams['breakdown_normalize_url'] = undefined
    if (isTrends && filters.display === ChartDisplayType.WorldMap) {
        // For the map, make sure we are breaking down by country
        // Support automatic switching to country code breakdown both from no breakdown and from country name breakdown
        cleanedParams['breakdown'] = '$geoip_country_code'
        useMostRelevantBreakdownType(cleanedParams, filters)
        return
    }
    if (canBreakdown) {
        if (filters.breakdown_type && (filters.breakdown || filters.breakdowns)) {
            cleanedParams['breakdown_type'] = filters.breakdown_type
        }

        const hasBreakdowns = Array.isArray(filters.breakdowns) && filters.breakdowns?.length > 0
        if (hasBreakdowns && canMultiPropertyBreakdown) {
            cleanedParams['breakdowns'] = filters.breakdowns
        } else if (hasBreakdowns && isTrends) {
            cleanedParams['breakdown'] = filters.breakdowns && filters.breakdowns[0].property
            cleanedParams['breakdown_normalize_url'] = cleanBreakdownNormalizeURL(
                cleanedParams['breakdown'] as string,
                filters.breakdown_normalize_url
            )
        } else if (filters.breakdown) {
            cleanedParams['breakdown'] = filters.breakdown
            cleanedParams['breakdown_normalize_url'] = cleanBreakdownNormalizeURL(
                filters.breakdown as string,
                filters.breakdown_normalize_url
            )
        }

        if (filters.breakdown_type === 'group' && filters.breakdown_group_type_index != undefined) {
            cleanedParams['breakdown_group_type_index'] = filters.breakdown_group_type_index
        }
    }
}

type CommonFiltersTypeKeys = keyof TrendsFilterType &
    keyof FunnelsFilterType &
    keyof RetentionFilterType &
    keyof PathsFilterType &
    keyof StickinessFilterType &
    keyof LifecycleFilterType

type CommonFiltersType = {
    [K in CommonFiltersTypeKeys]: FilterType[K]
}

/** Heuristic for determining wether this is a new insight, usually set by url.
 * In the most basic case something like `/insights/new?insight=TRENDS`. */
const isNewInsight = (filters: Partial<AnyFilterType>): boolean => {
    if (Object.keys(filters).length === 0) {
        return true
    }

    if (
        isTrendsFilter(filters) ||
        isFunnelsFilter(filters) ||
        isStickinessFilter(filters) ||
        isLifecycleFilter(filters)
    ) {
        return !filters.actions && !filters.events
    }

    if (isRetentionFilter(filters)) {
        return !filters.returning_entity && !filters.target_entity
    }

    if (isPathsFilter(filters)) {
        return !filters.include_event_types
    }

    return true
}

export const setTestAccountFilterForNewInsight = (
    filter: Partial<AnyFilterType>,
    test_account_filters_default_checked?: boolean
): void => {
    if (localStorage.getItem('default_filter_test_accounts') !== null) {
        // use current user default
        filter.filter_test_accounts = localStorage.getItem('default_filter_test_accounts') === 'true'
    } else if (!filter.filter_test_accounts && test_account_filters_default_checked !== undefined) {
        // overwrite with team default, only if not set
        filter.filter_test_accounts = test_account_filters_default_checked
    }
}

export function cleanFilters(
    filters: Partial<AnyFilterType>,
    test_account_filters_default_checked?: boolean
): Partial<FilterType> {
    const commonFilters: Partial<CommonFiltersType> = {
        ...(filters.sampling_factor ? { sampling_factor: filters.sampling_factor } : {}),
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        ...(filters.properties ? { properties: filters.properties } : {}),
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
    }

    // set test account filter default for new insights from team and local storage settings
    if (isNewInsight(filters)) {
        setTestAccountFilterForNewInsight(commonFilters, test_account_filters_default_checked)
    }

    if (isRetentionFilter(filters)) {
        const retentionFilter: Partial<RetentionFilterType> = {
            insight: InsightType.RETENTION,
            target_entity: filters.target_entity || {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
            },
            returning_entity: filters.returning_entity || { id: '$pageview', type: 'events', name: '$pageview' },
            date_to: filters.date_to,
            period: filters.period || RetentionPeriod.Day,
            retention_type: filters.retention_type || (filters as any)['retentionType'] || RETENTION_FIRST_TIME,
            breakdowns: filters.breakdowns,
            breakdown_type: filters.breakdown_type,
            retention_reference: filters.retention_reference,
            total_intervals: Math.min(Math.max(filters.total_intervals ?? 11, 0), 100),
            ...(filters.aggregation_group_type_index != undefined
                ? { aggregation_group_type_index: filters.aggregation_group_type_index }
                : {}),
            ...commonFilters,
        }
        return retentionFilter
    } else if (isFunnelsFilter(filters)) {
        const funnelsFilter: Partial<FunnelsFilterType> = {
            insight: InsightType.FUNNELS,
            ...(filters.date_from ? { date_from: filters.date_from } : {}),
            ...(filters.date_to ? { date_to: filters.date_to } : {}),
            ...(filters.actions ? { actions: filters.actions } : {}),
            ...(filters.events ? { events: filters.events } : {}),
            ...(filters.layout ? { layout: filters.layout } : {}),
            ...(filters.new_entity ? { new_entity: filters.new_entity } : {}),
            ...(filters.interval ? { interval: filters.interval } : {}),
            ...(filters.funnel_step ? { funnel_step: filters.funnel_step } : {}),
            ...(filters.funnel_from_step ? { funnel_from_step: filters.funnel_from_step } : {}),
            ...(filters.funnel_to_step ? { funnel_to_step: filters.funnel_to_step } : {}),
            ...(filters.funnel_step_reference ? { funnel_step_reference: filters.funnel_step_reference } : {}),
            ...(filters.funnel_viz_type
                ? { funnel_viz_type: filters.funnel_viz_type }
                : { funnel_viz_type: FunnelVizType.Steps }),
            ...(filters.entrance_period_start ? { entrance_period_start: filters.entrance_period_start } : {}),
            ...(filters.drop_off != undefined ? { drop_off: filters.drop_off } : {}),
            ...(filters.funnel_step_breakdown !== undefined
                ? { funnel_step_breakdown: filters.funnel_step_breakdown }
                : {}),
            ...(filters.bin_count && filters.bin_count !== BIN_COUNT_AUTO ? { bin_count: filters.bin_count } : {}),
            ...(filters.funnel_window_interval_unit
                ? { funnel_window_interval_unit: filters.funnel_window_interval_unit }
                : {}),
            ...(filters.funnel_window_interval ? { funnel_window_interval: filters.funnel_window_interval } : {}),
            ...(filters.funnel_order_type ? { funnel_order_type: filters.funnel_order_type } : {}),
            ...(filters.hidden_legend_keys ? { hidden_legend_keys: filters.hidden_legend_keys } : {}),
            ...(filters.funnel_aggregate_by_hogql
                ? { funnel_aggregate_by_hogql: filters.funnel_aggregate_by_hogql }
                : {}),
            ...(filters.breakdown_attribution_type
                ? { breakdown_attribution_type: filters.breakdown_attribution_type }
                : {}),
            ...(filters.breakdown_attribution_value !== undefined
                ? { breakdown_attribution_value: filters.breakdown_attribution_value }
                : {}),
            exclusions: deepCleanFunnelExclusionEvents(filters),
            interval: autocorrectInterval(filters),
            funnel_correlation_person_entity: filters.funnel_correlation_person_entity || undefined,
            funnel_correlation_person_converted: filters.funnel_correlation_person_converted || undefined,
            funnel_custom_steps: filters.funnel_custom_steps || undefined,
            ...(filters.aggregation_group_type_index != undefined
                ? { aggregation_group_type_index: filters.aggregation_group_type_index }
                : {}),
            ...commonFilters,
        }

        cleanBreakdownParams(funnelsFilter, filters)

        // if we came from an URL with just `#q={insight:TRENDS}` (no `events`/`actions`), add the default states `[]`
        if (isStepsUndefined(funnelsFilter)) {
            funnelsFilter.events = [getDefaultEvent()]
            funnelsFilter.actions = []
        }

        // make sure exclusion steps are clamped within new step range
        const returnedParams: Partial<FunnelsFilterType> = {
            ...funnelsFilter,
            ...getClampedStepRangeFilter({ filters: funnelsFilter }),
            exclusions: (funnelsFilter.exclusions || []).map((e) =>
                getClampedStepRangeFilter({
                    stepRange: e,
                    filters: funnelsFilter,
                })
            ),
        }
        return returnedParams
    } else if (isPathsFilter(filters)) {
        const pathsFilter: Partial<PathsFilterType> = {
            insight: InsightType.PATHS,
            start_point: filters.start_point || undefined,
            end_point: filters.end_point || undefined,
            step_limit: filters.step_limit || DEFAULT_STEP_LIMIT,
            // TODO: use FF for path_type undefined
            path_type: filters.path_type ? filters.path_type || PathType.PageView : undefined,
            include_event_types: filters.include_event_types || (filters.funnel_filter ? [] : [PathType.PageView]),
            paths_hogql_expression: filters.paths_hogql_expression || undefined,
            path_groupings: filters.path_groupings || [],
            exclude_events: filters.exclude_events || [],
            ...(filters.include_event_types ? { include_event_types: filters.include_event_types } : {}),
            date_from: filters.date_from,
            date_to: filters.date_to,
            path_start_key: filters.path_start_key || undefined,
            path_end_key: filters.path_end_key || undefined,
            path_dropoff_key: filters.path_dropoff_key || undefined,
            funnel_filter: filters.funnel_filter || { date_from: filters.date_from },
            funnel_paths: filters.funnel_paths,
            path_replacements: filters.path_replacements || undefined,
            local_path_cleaning_filters: filters.local_path_cleaning_filters || [],
            edge_limit: filters.edge_limit || undefined,
            min_edge_weight: filters.min_edge_weight || undefined,
            max_edge_weight: filters.max_edge_weight || undefined,
            ...commonFilters,
        }
        return pathsFilter
    } else if (isTrendsFilter(filters) || isLifecycleFilter(filters) || isStickinessFilter(filters)) {
        const trendLikeFilter: Partial<TrendsFilterType> = {
            insight: isLifecycleFilter(filters)
                ? InsightType.LIFECYCLE
                : isStickinessFilter(filters)
                ? InsightType.STICKINESS
                : InsightType.TRENDS,
            ...filters,
            interval: autocorrectInterval(filters),
            ...(isTrendsFilter(filters) ? { display: filters.display || ChartDisplayType.ActionsLineGraph } : {}),
            actions: Array.isArray(filters.actions) ? filters.actions : undefined,
            events: Array.isArray(filters.events) ? filters.events : undefined,
            ...(isTrendsFilter(filters) && isStickinessFilter(filters) && filters.hidden_legend_keys
                ? { hidden_legend_keys: filters.hidden_legend_keys }
                : {}),
            ...(filters.show_values_on_series ? { show_values_on_series: filters.show_values_on_series } : {}),
            ...(isTrendsFilter(filters) && filters?.show_percent_stack_view
                ? { show_percent_stack_view: filters.show_percent_stack_view }
                : {}),
            ...commonFilters,
        }

        if (
            'show_values_on_series' in trendLikeFilter &&
            !!trendLikeFilter.display &&
            NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(trendLikeFilter.display)
        ) {
            delete trendLikeFilter.show_values_on_series
        }

        if (
            !!trendLikeFilter.display &&
            trendLikeFilter.display === ChartDisplayType.ActionsPie &&
            trendLikeFilter.show_values_on_series === undefined
        ) {
            trendLikeFilter.show_values_on_series = true
        }

        if (
            'show_percent_stack_view' in trendLikeFilter &&
            !!trendLikeFilter.display &&
            !PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(trendLikeFilter.display)
        ) {
            delete trendLikeFilter.show_percent_stack_view
        }

        if (
            !!trendLikeFilter.display &&
            trendLikeFilter.display === ChartDisplayType.ActionsPie &&
            trendLikeFilter.show_percent_stack_view === undefined
        ) {
            trendLikeFilter.show_percent_stack_view = true
        }

        cleanBreakdownParams(trendLikeFilter, filters)

        // TODO: Deprecated; should be removed once backend is updated
        trendLikeFilter['shown_as'] = isStickinessFilter(filters)
            ? ShownAsValue.STICKINESS
            : isLifecycleFilter(filters)
            ? ShownAsValue.LIFECYCLE
            : undefined

        if (filters.date_from === 'all' || isLifecycleFilter(filters)) {
            trendLikeFilter['compare'] = false
        }

        if (trendLikeFilter.interval && trendLikeFilter.smoothing_intervals) {
            if (
                !smoothingOptions[trendLikeFilter.interval].find(
                    (option) => option.value === trendLikeFilter.smoothing_intervals
                )
            ) {
                if (trendLikeFilter.smoothing_intervals !== 1) {
                    trendLikeFilter.smoothing_intervals = 1
                }
            }
        }

        if (trendLikeFilter.insight === InsightType.LIFECYCLE) {
            if (trendLikeFilter.events?.length) {
                trendLikeFilter.events = [
                    {
                        ...trendLikeFilter.events[0],
                        math: 'total',
                    },
                ]
                trendLikeFilter.actions = []
            } else if (trendLikeFilter.actions?.length) {
                trendLikeFilter.events = []
                trendLikeFilter.actions = [
                    {
                        ...trendLikeFilter.actions[0],
                        math: 'total',
                    },
                ]
            }
        }

        if (isStepsUndefined(trendLikeFilter)) {
            trendLikeFilter.events = [getDefaultEvent()]
            trendLikeFilter.actions = []
        }

        return trendLikeFilter
    } else if ((filters as any).insight === 'SESSIONS') {
        // DEPRECATED: Used to show deprecation warning for dashboard items
        return cleanFilters({ insight: InsightType.TRENDS })
    }

    throw new Error(`Unknown insight type "${(filters as any).insight}" given to cleanFilters`)
}
