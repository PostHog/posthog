import { ChartDisplayType, Entity, EntityTypes, FilterType, PathType, ViewType } from '~/types'
import { getClampedStepRangeFilter, isStepsEmpty } from 'scenes/funnels/funnelUtils'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { cleanFunnelParams } from 'scenes/funnels/funnelLogic'
import { defaultFilterTestAccounts } from 'scenes/insights/insightLogic'
import { RETENTION_FIRST_TIME, ShownAsValue } from 'lib/constants'
import { autocorrectInterval } from 'lib/utils'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsLogic'

export function getDefaultEvent(): Entity {
    const event = getDefaultEventName()
    return {
        id: event,
        name: event,
        type: EntityTypes.EVENTS,
        order: 0,
    }
}

interface CleanFilterOptions {
    setDefault?: boolean
}

export function cleanFilters(filters: Partial<FilterType>, options: CleanFilterOptions = {}): Partial<FilterType> {
    if (filters.insight === ViewType.RETENTION) {
        return {
            target_entity: filters.target_entity || {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
            },
            returning_entity: filters.returning_entity || { id: '$pageview', type: 'events', name: '$pageview' },
            date_to: filters.date_to,
            period: filters.period || 'Day',
            retention_type: filters.retention_type || (filters as any)['retentionType'] || RETENTION_FIRST_TIME,
            display: filters.display || ChartDisplayType.ActionsTable,
            properties: filters.properties || [],
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            insight: ViewType.RETENTION,
        }
    } else if (filters.insight === ViewType.FUNNELS) {
        const cleanedParams = cleanFunnelParams(filters)

        if (isStepsEmpty(cleanedParams) && options.setDefault) {
            cleanedParams.events = [getDefaultEvent()]
        }

        // make sure exclusion steps are clamped within new step range
        return {
            ...cleanedParams,
            ...getClampedStepRangeFilter({ filters: cleanedParams }),
            exclusions: (cleanedParams.exclusions || []).map((e) =>
                getClampedStepRangeFilter({ stepRange: e, filters: cleanedParams })
            ),
        }
    } else if (filters.insight === ViewType.PATHS) {
        return {
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
            insight: ViewType.PATHS,
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
            path_start_key: filters.path_start_key || undefined,
            path_end_key: filters.path_end_key || undefined,
            path_dropoff_key: filters.path_dropoff_key || undefined,
            funnel_filter: filters.funnel_filter || { date_from: filters.date_from },
            funnel_paths: filters.funnel_paths,
        }
    } else if (
        filters.insight === ViewType.TRENDS ||
        filters.insight === ViewType.SESSIONS ||
        filters.insight === ViewType.STICKINESS ||
        filters.insight === ViewType.LIFECYCLE ||
        !filters.insight
    ) {
        const cleanSearchParams: Partial<FilterType> = {
            insight: ViewType.TRENDS,
            ...filters,
            interval: autocorrectInterval(filters),
            display:
                filters.session && filters.session === 'dist'
                    ? ChartDisplayType.ActionsTable
                    : filters.display || ChartDisplayType.ActionsLineGraphLinear,
            actions: Array.isArray(filters.actions) ? filters.actions : undefined,
            events: Array.isArray(filters.events) ? filters.events : undefined,
            properties: filters.properties || [],
            ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        }

        if (Object.keys(filters).length === 0 || (!filters.actions && !filters.events)) {
            cleanSearchParams.filter_test_accounts = defaultFilterTestAccounts()
        }

        // TODO: Deprecated; should be removed once backend is updated
        if (filters.insight === ViewType.STICKINESS) {
            cleanSearchParams['shown_as'] = ShownAsValue.STICKINESS
        }
        if (filters.insight === ViewType.LIFECYCLE) {
            cleanSearchParams['shown_as'] = ShownAsValue.LIFECYCLE
        }

        if (filters.insight === ViewType.SESSIONS && !filters.session) {
            cleanSearchParams['session'] = 'avg'
        }

        if (filters.date_from === 'all' || filters.insight === ViewType.LIFECYCLE) {
            cleanSearchParams['compare'] = false
        }

        if (cleanSearchParams.insight === ViewType.LIFECYCLE) {
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

        if (isStepsEmpty(cleanSearchParams) && options.setDefault) {
            cleanSearchParams.events = [getDefaultEvent()]
        }

        return cleanSearchParams
    }

    throw new Error(`Unknown insight type "${filters.insight}" given to cleanFilters`)
}
