import { ChartDisplayType, Entity, EntityTypes, FilterType, FunnelVizType, InsightType, PathType } from '~/types'
import { deepCleanFunnelExclusionEvents, getClampedStepRangeFilter, isStepsUndefined } from 'scenes/funnels/funnelUtils'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { defaultFilterTestAccounts } from 'scenes/insights/insightLogic'
import { BinCountAuto, FEATURE_FLAGS, RETENTION_FIRST_TIME, ShownAsValue } from 'lib/constants'
import { autocorrectInterval } from 'lib/utils'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsLogic'
import { isTrendsInsight } from 'scenes/insights/sharedUtils'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export function getDefaultEvent(): Entity {
    const event = getDefaultEventName()
    return {
        id: event,
        name: event,
        type: EntityTypes.EVENTS,
        order: 0,
    }
}

const cleanBreakdownParams = (
    cleanedParams: Partial<FilterType>,
    filters: Partial<FilterType>,
    featureFlags: Record<string, any>
): void => {
    const isStepsFunnel = filters.insight === InsightType.FUNNELS && filters.funnel_viz_type === FunnelVizType.Steps
    const isTrends = filters.insight === InsightType.TRENDS
    const canBreakdown = isStepsFunnel || isTrends

    const canMultiPropertyBreakdown = isStepsFunnel

    cleanedParams['breakdowns'] = undefined
    cleanedParams['breakdown'] = undefined
    cleanedParams['breakdown_type'] = undefined
    cleanedParams['breakdown_group_type_index'] = undefined

    if (canBreakdown) {
        if (filters.breakdown_type && (filters.breakdown || filters.breakdowns)) {
            cleanedParams['breakdown_type'] = filters.breakdown_type
        }

        const hasBreakdowns = Array.isArray(filters.breakdowns) && filters.breakdowns?.length > 0
        if (hasBreakdowns && canMultiPropertyBreakdown) {
            cleanedParams['breakdowns'] = filters.breakdowns
        } else if (hasBreakdowns && isTrends) {
            cleanedParams['breakdown'] = filters.breakdowns && filters.breakdowns[0].property
        } else if (
            filters.breakdown &&
            isStepsFunnel &&
            featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES] &&
            ['string', 'number'].includes(typeof filters.breakdown) &&
            cleanedParams['breakdown_type']
        ) {
            cleanedParams['breakdowns'] = [
                { property: filters.breakdown as string | number, type: cleanedParams['breakdown_type'] },
            ]
        } else if (filters.breakdown) {
            cleanedParams['breakdown'] = filters.breakdown
        }

        if (filters.breakdown_type === 'group' && filters.breakdown_group_type_index != undefined) {
            cleanedParams['breakdown_group_type_index'] = filters.breakdown_group_type_index
        }
    }
}

export function cleanFilters(
    filters: Partial<FilterType>,
    oldFilters?: Partial<FilterType>,
    featureFlags?: FeatureFlagsSet
): Partial<FilterType> {
    const insightChanged = oldFilters?.insight && filters.insight !== oldFilters?.insight

    if (filters.insight === InsightType.RETENTION) {
        return {
            insight: InsightType.RETENTION,
            target_entity: filters.target_entity || {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
            },
            returning_entity: filters.returning_entity || { id: '$pageview', type: 'events', name: '$pageview' },
            date_to: filters.date_to,
            period: filters.period || 'Day',
            retention_type: filters.retention_type || (filters as any)['retentionType'] || RETENTION_FIRST_TIME,
            breakdowns: filters.breakdowns,
            breakdown_type: filters.breakdown_type,
            display: insightChanged ? ChartDisplayType.ActionsTable : filters.display || ChartDisplayType.ActionsTable,
            properties: filters.properties || [],
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            ...(filters.aggregation_group_type_index != undefined
                ? { aggregation_group_type_index: filters.aggregation_group_type_index }
                : {}),
        }
    } else if (filters.insight === InsightType.FUNNELS) {
        const cleanedParams: Partial<FilterType> = {
            insight: InsightType.FUNNELS,
            ...(filters.date_from ? { date_from: filters.date_from } : {}),
            ...(filters.date_to ? { date_to: filters.date_to } : {}),
            ...(filters.actions ? { actions: filters.actions } : {}),
            ...(filters.events ? { events: filters.events } : {}),
            ...(insightChanged || filters.display
                ? { display: insightChanged ? ChartDisplayType.FunnelViz : filters.display }
                : {}),
            ...(filters.layout ? { layout: filters.layout } : {}),
            ...(filters.interval ? { interval: filters.interval } : {}),
            ...(filters.properties ? { properties: filters.properties } : {}),
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            ...(filters.funnel_step ? { funnel_step: filters.funnel_step } : {}),
            ...(filters.funnel_from_step ? { funnel_from_step: filters.funnel_from_step } : {}),
            ...(filters.funnel_to_step ? { funnel_to_step: filters.funnel_to_step } : {}),
            ...(filters.funnel_viz_type
                ? { funnel_viz_type: filters.funnel_viz_type }
                : { funnel_viz_type: FunnelVizType.Steps }),
            ...(filters.funnel_step ? { funnel_to_step: filters.funnel_step } : {}),
            ...(filters.entrance_period_start ? { entrance_period_start: filters.entrance_period_start } : {}),
            ...(filters.drop_off != undefined ? { drop_off: filters.drop_off } : {}),
            ...(filters.funnel_step_breakdown !== undefined
                ? { funnel_step_breakdown: filters.funnel_step_breakdown }
                : {}),
            ...(filters.bin_count && filters.bin_count !== BinCountAuto ? { bin_count: filters.bin_count } : {}),
            ...(filters.funnel_window_interval_unit
                ? { funnel_window_interval_unit: filters.funnel_window_interval_unit }
                : {}),
            ...(filters.funnel_window_interval ? { funnel_window_interval: filters.funnel_window_interval } : {}),
            ...(filters.funnel_order_type ? { funnel_order_type: filters.funnel_order_type } : {}),
            ...(filters.hiddenLegendKeys ? { hiddenLegendKeys: filters.hiddenLegendKeys } : {}),
            ...(filters.funnel_advanced ? { funnel_advanced: filters.funnel_advanced } : {}),
            exclusions: deepCleanFunnelExclusionEvents(filters),
            interval: autocorrectInterval(filters),
            funnel_correlation_person_entity: filters.funnel_correlation_person_entity || undefined,
            funnel_correlation_person_converted: filters.funnel_correlation_person_converted || undefined,
            funnel_custom_steps: filters.funnel_custom_steps || undefined,
            ...(filters.aggregation_group_type_index != undefined
                ? { aggregation_group_type_index: filters.aggregation_group_type_index }
                : {}),
        }

        cleanBreakdownParams(cleanedParams, filters, featureFlags || {})

        // if we came from an URL with just `#q={insight:TRENDS}` (no `events`/`actions`), add the default states `[]`
        if (isStepsUndefined(cleanedParams)) {
            cleanedParams.events = [getDefaultEvent()]
            cleanedParams.actions = []
        }

        // make sure exclusion steps are clamped within new step range
        return {
            ...cleanedParams,
            ...getClampedStepRangeFilter({ filters: cleanedParams }),
            exclusions: (cleanedParams.exclusions || []).map((e) =>
                getClampedStepRangeFilter({ stepRange: e, filters: cleanedParams })
            ),
        }
    } else if (filters.insight === InsightType.PATHS) {
        return {
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
    } else if (isTrendsInsight(filters.insight) || !filters.insight) {
        const cleanSearchParams: Partial<FilterType> = {
            insight: InsightType.TRENDS,
            ...filters,
            interval: autocorrectInterval(filters),
            display:
                filters.session && filters.session === 'dist'
                    ? ChartDisplayType.ActionsTable
                    : insightChanged
                    ? ChartDisplayType.ActionsLineGraphLinear
                    : filters.display || ChartDisplayType.ActionsLineGraphLinear,
            actions: Array.isArray(filters.actions) ? filters.actions : undefined,
            events: Array.isArray(filters.events) ? filters.events : undefined,
            properties: filters.properties || [],
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        }

        cleanBreakdownParams(cleanSearchParams, filters, featureFlags || {})

        if (Object.keys(filters).length === 0 || (!filters.actions && !filters.events)) {
            cleanSearchParams.filter_test_accounts = defaultFilterTestAccounts()
        }

        // TODO: Deprecated; should be removed once backend is updated
        if (filters.insight === InsightType.STICKINESS) {
            cleanSearchParams['shown_as'] = ShownAsValue.STICKINESS
        } else if (filters.insight === InsightType.LIFECYCLE) {
            cleanSearchParams['shown_as'] = ShownAsValue.LIFECYCLE
        } else {
            cleanSearchParams['shown_as'] = undefined
        }

        if (filters.insight === InsightType.SESSIONS && !filters.session) {
            cleanSearchParams['session'] = 'avg'
        }

        if (filters.date_from === 'all' || filters.insight === InsightType.LIFECYCLE) {
            cleanSearchParams['compare'] = false
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
    } else if ((filters.insight as string) === 'HISTORY') {
        return cleanFilters({ insight: InsightType.TRENDS })
    }

    throw new Error(`Unknown insight type "${filters.insight}" given to cleanFilters`)
}
