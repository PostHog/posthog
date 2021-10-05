import { ChartDisplayType, EntityTypes, FilterType, ViewType } from '~/types'
import { cleanFunnelParams } from 'scenes/funnels/funnelLogic'
import { isStepsEmpty } from 'scenes/funnels/funnelUtils'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { defaultFilterTestAccounts } from 'scenes/insights/url'
import { ShownAsValue } from 'lib/constants'
import { getDefaultTrendsFilters } from 'scenes/trends/trendsLogic'
import { cleanPathParams } from 'scenes/paths/pathsLogic'
import { autocorrectInterval } from 'lib/utils'

export function cleanFilters(queryParams: Partial<FilterType>): Partial<FilterType> {
    if (queryParams.insight === ViewType.FUNNELS) {
        const cleanedParams = cleanFunnelParams(queryParams)
        if (isStepsEmpty(cleanedParams)) {
            const event = getDefaultEventName()
            cleanedParams.events = [
                {
                    id: event,
                    name: event,
                    type: EntityTypes.EVENTS,
                    order: 0,
                },
            ]
        }
        return cleanedParams
    } else if (queryParams.insight === ViewType.PATHS) {
        return cleanPathParams(queryParams)
    } else if (
        !queryParams.insight ||
        queryParams.insight === ViewType.TRENDS ||
        queryParams.insight === ViewType.SESSIONS ||
        queryParams.insight === ViewType.STICKINESS ||
        queryParams.insight === ViewType.LIFECYCLE
    ) {
        const cleanSearchParams = cleanTrendsFilters(queryParams)

        const keys = Object.keys(queryParams)

        if (keys.length === 0 || (!queryParams.actions && !queryParams.events)) {
            cleanSearchParams.filter_test_accounts = defaultFilterTestAccounts()
        }

        // TODO: Deprecated; should be removed once backend is updated
        if (queryParams.insight === ViewType.STICKINESS) {
            cleanSearchParams['shown_as'] = ShownAsValue.STICKINESS
        }
        if (queryParams.insight === ViewType.LIFECYCLE) {
            cleanSearchParams['shown_as'] = ShownAsValue.LIFECYCLE
        }

        if (queryParams.insight === ViewType.SESSIONS && !queryParams.session) {
            cleanSearchParams['session'] = 'avg'
        }

        if (queryParams.date_from === 'all' || queryParams.insight === ViewType.LIFECYCLE) {
            cleanSearchParams['compare'] = false
        }

        Object.assign(cleanSearchParams, getDefaultTrendsFilters(cleanSearchParams))

        if (cleanSearchParams.insight === ViewType.LIFECYCLE) {
            if (cleanSearchParams.events?.length) {
                return {
                    ...cleanSearchParams,
                    events: [
                        {
                            ...cleanSearchParams.events[0],
                            math: 'total',
                        },
                    ],
                    actions: [],
                }
            } else if (cleanSearchParams.actions?.length) {
                return {
                    ...cleanSearchParams,
                    events: [],
                    actions: [
                        {
                            ...cleanSearchParams.actions[0],
                            math: 'total',
                        },
                    ],
                }
            }
        }

        return cleanSearchParams
    } else {
        return queryParams
    }
}

export function cleanTrendsFilters(filters: Partial<FilterType>): Partial<FilterType> {
    return {
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
}

export function filterTrendsClientSideParams(filters: Partial<FilterType>): Partial<FilterType> {
    const {
        people_day: _skip_this_one, // eslint-disable-line
        people_action: _skip_this_too, // eslint-disable-line
        stickiness_days: __and_this, // eslint-disable-line
        ...newFilters
    } = filters

    return newFilters
}
