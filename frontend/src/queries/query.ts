import { DataNode, EventsNode, EventsQuery, PersonsNode } from './schema'
import { isEventsNode, isEventsQuery, isLegacyQuery, isPersonsNode } from './utils'
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
import { now } from 'lib/dayjs'

const EVENTS_DAYS_FIRST_FETCH = 5

export const DEFAULT_QUERY_LIMIT = 100

// Return data for a given query
export async function query<N extends DataNode = DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions
): Promise<N['response']> {
    if (isEventsNode(query) || isEventsQuery(query)) {
        if (!query.before && !query.after) {
            const earlyResults = await api.get(
                getEventsEndpoint({ ...query, after: now().subtract(EVENTS_DAYS_FIRST_FETCH, 'day').toISOString() })
            )
            if (earlyResults.results.length > 0) {
                return earlyResults
            }
        }
        return await api.get(getEventsEndpoint({ after: now().subtract(1, 'year').toISOString(), ...query }))
    } else if (isPersonsNode(query)) {
        return await api.get(getPersonsEndpoint(query))
    } else if (isLegacyQuery(query)) {
        const [response] = await legacyInsightQuery({
            filters: query.filters,
            currentTeamId: getCurrentTeamId(),
            methodOptions,
        })
        return await response.json()
    }
    throw new Error(`Unsupported query: ${query.kind}`)
}

export function getEventsEndpoint(query: EventsNode | EventsQuery): string {
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
        },
        query.limit ?? DEFAULT_QUERY_LIMIT
    )
}

export function getPersonsEndpoint(query: PersonsNode): string {
    return api.persons.determineListUrl({
        properties: [...(query.fixedProperties || []), ...(query.properties || [])],
        ...(query.search ? { search: query.search } : {}),
        ...(query.cohort ? { cohort: query.cohort } : {}),
        ...(query.distinctId ? { distinct_id: query.distinctId } : {}),
    })
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
        apiUrl = `api/projects/${currentTeamId}/insights/trend/?${toParams(filterTrendsClientSideParams(filters))}`
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isRetentionFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/retention/?${toParams(filters)}`
        fetchResponse = await api.getResponse(apiUrl, methodOptions)
    } else if (isFunnelsFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/funnel/${refresh ? '?refresh=true' : ''}`
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else if (isPathsFilter(filters)) {
        apiUrl = `api/projects/${currentTeamId}/insights/path`
        fetchResponse = await api.createResponse(apiUrl, filters, methodOptions)
    } else {
        throw new Error(`Unsupported insight type: ${filters.insight}`)
    }
    return [fetchResponse, apiUrl]
}
