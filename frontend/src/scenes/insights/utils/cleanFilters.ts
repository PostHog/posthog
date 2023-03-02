import {
    AnyFilterType,
    ChartDisplayType,
    Entity,
    EntityTypes,
    FilterType,
    FunnelsFilterType,
    FunnelVizType,
    InsightType,
    PathsFilterType,
    PathType,
    RetentionFilterType,
    RetentionPeriod,
    TrendsFilterType,
} from '~/types'
import { deepCleanFunnelExclusionEvents, getClampedStepRangeFilter, isStepsUndefined } from 'scenes/funnels/funnelUtils'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { defaultFilterTestAccounts } from 'scenes/insights/insightLogic'
import {
    BIN_COUNT_AUTO,
    NON_VALUES_ON_SERIES_DISPLAY_TYPES,
    FEATURE_FLAGS,
    RETENTION_FIRST_TIME,
    ShownAsValue,
} from 'lib/constants'
import { autocorrectInterval } from 'lib/utils'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsLogic'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
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
    cleanedParams['breakdown_type'] =
        (series?.math &&
            (series.math === 'unique_group'
                ? 'group'
                : ['dau', 'weekly_active', 'monthly_active'].includes(series.math)
                ? 'person'
                : null)) ||
        'event'
    cleanedParams['breakdown_group_type_index'] = series?.math_group_type_index
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

const cleanBreakdownParams = (
    cleanedParams: Partial<FilterType>,
    filters: Partial<FilterType>,
    featureFlags: Record<string, any>
): void => {
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
        } else if (
            filters.breakdown &&
            isStepsFunnel &&
            featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES] &&
            ['string', 'number'].includes(typeof filters.breakdown) &&
            cleanedParams['breakdown_type']
        ) {
            cleanedParams['breakdowns'] = [
                {
                    property: filters.breakdown as string | number,
                    type: cleanedParams['breakdown_type'],
                    normalize_url: cleanBreakdownNormalizeURL(
                        filters.breakdown as string,
                        filters.breakdown_normalize_url
                    ),
                },
            ]
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

export function cleanFilters(
    filters: Partial<AnyFilterType>,
    // @ts-expect-error
    oldFilters?: Partial<AnyFilterType>,
    featureFlags?: FeatureFlagsSet
): Partial<FilterType> {
    if (isRetentionFilter(filters)) {
        const cleanedParams: Partial<RetentionFilterType> = {
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
            properties: filters.properties || [],
            total_intervals: Math.min(Math.max(filters.total_intervals ?? 11, 0), 100),
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            ...(filters.aggregation_group_type_index != undefined
                ? { aggregation_group_type_index: filters.aggregation_group_type_index }
                : {}),
            ...(filters.sampling_factor ? { sampling_factor: filters.sampling_factor } : {}),
        }
        return cleanedParams
    } else if (isFunnelsFilter(filters)) {
        const cleanedParams: Partial<FunnelsFilterType> = {
            insight: InsightType.FUNNELS,
            ...(filters.date_from ? { date_from: filters.date_from } : {}),
            ...(filters.date_to ? { date_to: filters.date_to } : {}),
            ...(filters.actions ? { actions: filters.actions } : {}),
            ...(filters.events ? { events: filters.events } : {}),
            ...(filters.layout ? { layout: filters.layout } : {}),
            ...(filters.new_entity ? { new_entity: filters.new_entity } : {}),
            ...(filters.interval ? { interval: filters.interval } : {}),
            ...(filters.properties ? { properties: filters.properties } : {}),
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
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
            ...(filters.funnel_advanced ? { funnel_advanced: filters.funnel_advanced } : {}),
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
            ...(filters.sampling_factor ? { sampling_factor: filters.sampling_factor } : {}),
        }

        cleanBreakdownParams(cleanedParams, filters, featureFlags || {})

        // if we came from an URL with just `#q={insight:TRENDS}` (no `events`/`actions`), add the default states `[]`
        if (isStepsUndefined(cleanedParams)) {
            cleanedParams.events = [getDefaultEvent()]
            cleanedParams.actions = []
        }

        // make sure exclusion steps are clamped within new step range
        const returnedParams: Partial<FunnelsFilterType> = {
            ...cleanedParams,
            ...getClampedStepRangeFilter({ filters: cleanedParams }),
            exclusions: (cleanedParams.exclusions || []).map((e) =>
                getClampedStepRangeFilter({
                    stepRange: e,
                    filters: cleanedParams,
                })
            ),
        }
        return returnedParams
    } else if (isPathsFilter(filters)) {
        const cleanFilters: Partial<PathsFilterType> = {
            insight: InsightType.PATHS,
            properties: filters.properties || [],
            start_point: filters.start_point || undefined,
            end_point: filters.end_point || undefined,
            step_limit: filters.step_limit || DEFAULT_STEP_LIMIT,
            // TODO: use FF for path_type undefined
            path_type: filters.path_type ? filters.path_type || PathType.PageView : undefined,
            include_event_types: filters.include_event_types || (filters.funnel_filter ? [] : [PathType.PageView]),
            path_groupings: filters.path_groupings || [],
            exclude_events: filters.exclude_events || [],
            ...(filters.include_event_types ? { include_event_types: filters.include_event_types } : {}),
            date_from: filters.date_from,
            date_to: filters.date_to,
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
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
        }
        return cleanFilters
    } else if (isTrendsFilter(filters) || isLifecycleFilter(filters) || isStickinessFilter(filters)) {
        const cleanSearchParams: Partial<TrendsFilterType> = {
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
            properties: filters.properties || [],
            ...(isTrendsFilter(filters) && isStickinessFilter(filters) && filters.hidden_legend_keys
                ? { hidden_legend_keys: filters.hidden_legend_keys }
                : {}),
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            ...(filters.show_values_on_series ? { show_values_on_series: filters.show_values_on_series } : {}),
        }

        if (
            'show_values_on_series' in cleanSearchParams &&
            !!cleanSearchParams.display &&
            NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(cleanSearchParams.display)
        ) {
            delete cleanSearchParams.show_values_on_series
        }

        if (
            !!cleanSearchParams.display &&
            cleanSearchParams.display === ChartDisplayType.ActionsPie &&
            cleanSearchParams.show_values_on_series === undefined
        ) {
            cleanSearchParams.show_values_on_series = true
        }

        cleanBreakdownParams(cleanSearchParams, filters, featureFlags || {})

        if (Object.keys(filters).length === 0 || (!filters.actions && !filters.events)) {
            cleanSearchParams.filter_test_accounts = defaultFilterTestAccounts(filters.filter_test_accounts || false)
        }

        // TODO: Deprecated; should be removed once backend is updated
        cleanSearchParams['shown_as'] = isStickinessFilter(filters)
            ? ShownAsValue.STICKINESS
            : isLifecycleFilter(filters)
            ? ShownAsValue.LIFECYCLE
            : undefined

        if (filters.date_from === 'all' || isLifecycleFilter(filters)) {
            cleanSearchParams['compare'] = false
        }

        if (cleanSearchParams.interval && cleanSearchParams.smoothing_intervals) {
            if (
                !smoothingOptions[cleanSearchParams.interval].find(
                    (option) => option.value === cleanSearchParams.smoothing_intervals
                )
            ) {
                if (cleanSearchParams.smoothing_intervals !== 1) {
                    cleanSearchParams.smoothing_intervals = 1
                }
            }
        }

        if (cleanSearchParams.insight === InsightType.LIFECYCLE) {
            if (cleanSearchParams.events?.length) {
                cleanSearchParams.events = [
                    {
                        ...cleanSearchParams.events[0],
                        math: 'total',
                    },
                ]
                cleanSearchParams.actions = []
            } else if (cleanSearchParams.actions?.length) {
                cleanSearchParams.events = []
                cleanSearchParams.actions = [
                    {
                        ...cleanSearchParams.actions[0],
                        math: 'total',
                    },
                ]
            }
        }

        if (isStepsUndefined(cleanSearchParams)) {
            cleanSearchParams.events = [getDefaultEvent()]
            cleanSearchParams.actions = []
        }

        return cleanSearchParams
    } else if ((filters as any).insight === 'SESSIONS') {
        // DEPRECATED: Used to show deprecation warning for dashboard items
        return cleanFilters({ insight: InsightType.TRENDS })
    }

    throw new Error(`Unknown insight type "${(filters as any).insight}" given to cleanFilters`)
}
