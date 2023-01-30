import { DataNode, EventsQuery, PersonsNode } from './schema'
import {
    isInsightQueryNode,
    isEventsQuery,
    isLegacyQuery,
    isPersonsNode,
    isTimeToSeeDataSessionsQuery,
    isTimeToSeeDataQuery,
    isRecentPerformancePageViewNode,
} from './utils'
import api, { ApiMethodOptions } from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/logics'
import { AnyPartialFilterType } from '~/types'
import {
    filterTrendsClientSideParams,
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { toParams } from 'lib/utils'
import { queryNodeToFilter } from './nodes/InsightQuery/utils/queryNodeToFilter'
import { now } from 'lib/dayjs'
import { currentSessionId } from 'lib/internalMetrics'

const EVENTS_DAYS_FIRST_FETCH = 5

export const DEFAULT_QUERY_LIMIT = 100

// Return data for a given query
export async function query<N extends DataNode = DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean
): Promise<N['response']> {
    if (isEventsQuery(query)) {
        if (!query.before && !query.after) {
            const earlyResults = await api.query(
                { ...query, after: now().subtract(EVENTS_DAYS_FIRST_FETCH, 'day').toISOString() },
                methodOptions
            )
            if (earlyResults.results.length > 0) {
                return earlyResults
            }
        }
        return await api.query({ after: now().subtract(1, 'year').toISOString(), ...query }, methodOptions)
    } else if (isPersonsNode(query)) {
        return await api.get(getPersonsEndpoint(query), methodOptions)
    } else if (isInsightQueryNode(query)) {
        const filters = queryNodeToFilter(query)
        const [response] = await legacyInsightQuery({
            filters,
            currentTeamId: getCurrentTeamId(),
            refresh,
        })
        return await response.json()
    } else if (isLegacyQuery(query)) {
        const [response] = await legacyInsightQuery({
            filters: query.filters,
            currentTeamId: getCurrentTeamId(),
            methodOptions,
        })
        return await response.json()
    } else if (isTimeToSeeDataSessionsQuery(query)) {
        return await api.create('/api/time_to_see_data/sessions', {
            team_id: query.teamId ?? getCurrentTeamId(),
        })
    } else if (isTimeToSeeDataQuery(query)) {
        return await api.create('/api/time_to_see_data/session_events', {
            team_id: query.teamId ?? getCurrentTeamId(),
            session_id: query.sessionId ?? currentSessionId(),
            session_start: query.sessionStart ?? now().subtract(1, 'day').toISOString(),
            session_end: query.sessionEnd ?? now().toISOString(),
        })
    } else if (isRecentPerformancePageViewNode(query)) {
        return await api.performanceEvents.recentPageViews()
    }
    throw new Error(`Unsupported query: ${query.kind}`)
}

export function getEventsEndpoint(query: EventsQuery): string {
    return api.events.determineListEndpoint(
        {
            properties: [...(query.fixedProperties || []), ...(query.properties || [])],
            ...(query.event ? { event: query.event } : {}),
            ...(isEventsQuery(query) ? { select: query.select ?? [] } : {}),
            ...(isEventsQuery(query) ? { where: query.where ?? [] } : {}),
            ...(query.actionId ? { action_id: query.actionId } : {}),
            ...(query.personId ? { person_id: query.personId } : {}),
            ...(query.before ? { before: query.before } : {}),
            ...(query.after ? { after: query.after } : {}),
            ...(query.orderBy ? { orderBy: query.orderBy } : {}),
            ...(query.offset ? { offset: query.offset } : {}),
        },
        query.limit ?? DEFAULT_QUERY_LIMIT
    )
}

export function getPersonsEndpoint(query: PersonsNode): string {
    const params = {
        properties: [...(query.fixedProperties || []), ...(query.properties || [])],
        ...(query.search ? { search: query.search } : {}),
        ...(query.distinctId ? { distinct_id: query.distinctId } : {}),
        ...(query.limit ? { limit: query.limit } : {}),
        ...(query.offset ? { offset: query.offset } : {}),
    }
    if (query.cohort) {
        return api.cohorts.determineListUrl(query.cohort, params)
    }
    return api.persons.determineListUrl(params)
}

interface LegacyInsightQueryParams {
    filters: AnyPartialFilterType
    currentTeamId: number
    methodOptions?: ApiMethodOptions
    refresh?: boolean
}

export async function legacyInsightQuery({
    filters,
    currentTeamId,
    methodOptions,
    refresh,
}: LegacyInsightQueryParams): Promise<[Response, string]> {
    let apiUrl: string
    let fetchResponse: Response
    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/trend/?${toParams(filterTrendsClientSideParams(filters))}${
            refresh ? '&refresh=true' : ''
        }`
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isRetentionFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/retention/?${toParams(filters)}${
            refresh ? '&refresh=true' : ''
        }`
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isFunnelsFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/funnel/${refresh ? '?refresh=true' : ''}`
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else if (isPathsFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/path${refresh ? '&refresh=true' : ''}`
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else {
        throw new Error(`Unsupported insight type: ${filters.insight}`)
    }
    return [fetchResponse, apiUrl]
}
