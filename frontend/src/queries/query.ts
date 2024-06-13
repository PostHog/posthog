import api, { ApiMethodOptions } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { now } from 'lib/dayjs'
import { currentSessionId } from 'lib/internalMetrics'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { delay } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import posthog from 'posthog-js'

import { OnlineExportContext, QueryExportContext } from '~/types'

import { DataNode, HogQLQuery, HogQLQueryResponse, NodeKind, PersonsNode, QueryStatus } from './schema'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightVizNode,
    isPersonsNode,
    isTimeToSeeDataQuery,
    isTimeToSeeDataSessionsNode,
    isTimeToSeeDataSessionsQuery,
} from './utils'

const QUERY_ASYNC_MAX_INTERVAL_SECONDS = 5
const QUERY_ASYNC_TOTAL_POLL_SECONDS = 10 * 60 + 6 // keep in sync with backend-side timeout (currently 10min) + a small buffer

//get export context for a given query
export function queryExportContext<N extends DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean
): OnlineExportContext | QueryExportContext {
    if (isInsightVizNode(query) || isDataTableNode(query) || isDataVisualizationNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isPersonsNode(query)) {
        return { path: getPersonsEndpoint(query) }
    } else if (isTimeToSeeDataSessionsQuery(query)) {
        return {
            path: '/api/time_to_see_data/sessions',
            method: 'POST',
            body: {
                team_id: query.teamId ?? getCurrentTeamId(),
            },
        }
    } else if (isTimeToSeeDataQuery(query)) {
        return {
            path: '/api/time_to_see_data/session_events',
            method: 'POST',
            body: {
                team_id: query.teamId ?? getCurrentTeamId(),
                session_id: query.sessionId ?? currentSessionId(),
                session_start: query.sessionStart ?? now().subtract(1, 'day').toISOString(),
                session_end: query.sessionEnd ?? now().toISOString(),
            },
        }
    } else if (isTimeToSeeDataSessionsNode(query)) {
        return {
            path: '/api/time_to_see_data/session_events',
            method: 'POST',
            body: {
                team_id: query.source.teamId ?? getCurrentTeamId(),
                session_id: query.source.sessionId ?? currentSessionId(),
                session_start: query.source.sessionStart ?? now().subtract(1, 'day').toISOString(),
                session_end: query.source.sessionEnd ?? now().toISOString(),
            },
        }
    }
    return { source: query }
}

const SYNC_ONLY_QUERY_KINDS = [
    'HogQuery',
    'HogQLMetadata',
    'EventsQuery',
    'HogQLAutocomplete',
    'DatabaseSchemaQuery',
] satisfies NodeKind[keyof NodeKind][]

export async function pollForResults(
    queryId: string,
    showProgress: boolean,
    methodOptions?: ApiMethodOptions,
    callback?: (response: QueryStatus) => void
): Promise<QueryStatus> {
    const pollStart = performance.now()
    let currentDelay = 300 // start low, because all queries will take at minimum this

    while (performance.now() - pollStart < QUERY_ASYNC_TOTAL_POLL_SECONDS * 1000) {
        await delay(currentDelay, methodOptions?.signal)
        currentDelay = Math.min(currentDelay * 2, QUERY_ASYNC_MAX_INTERVAL_SECONDS * 1000)

        const statusResponse = (await api.queryStatus.get(queryId, showProgress)).query_status

        if (statusResponse.complete || statusResponse.error) {
            return statusResponse
        }
        if (callback) {
            callback(statusResponse)
        }
    }
    throw new Error('Query timed out')
}

/**
 * Execute a query node and return the response, use async query if enabled
 */
async function executeQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
    queryId?: string,
    setPollResponse?: (response: QueryStatus) => void
): Promise<NonNullable<N['response']>> {
    const isAsyncQuery =
        !SYNC_ONLY_QUERY_KINDS.includes(queryNode.kind) &&
        !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.QUERY_ASYNC]

    const showProgress = !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.INSIGHT_LOADING_BAR]

    const response = await api.query(queryNode, methodOptions, queryId, refresh, isAsyncQuery)

    if (!response.query_status?.query_async) {
        // Executed query synchronously
        return response
    }
    if (response.query_status?.complete || response.query_status?.error) {
        // Async query returned immediately
        return response.results
    }

    const statusResponse = await pollForResults(response.query_status.id, showProgress, methodOptions, setPollResponse)
    return statusResponse.results
}

// Return data for a given query
export async function performQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
    queryId?: string,
    setPollResponse?: (status: QueryStatus) => void
): Promise<NonNullable<N['response']>> {
    if (isTimeToSeeDataSessionsNode(queryNode)) {
        return performQuery(queryNode.source)
    }

    let response: NonNullable<N['response']>
    const logParams: Record<string, any> = {}
    const startTime = performance.now()

    try {
        if (isPersonsNode(queryNode)) {
            response = await api.get(getPersonsEndpoint(queryNode), methodOptions)
        } else if (isTimeToSeeDataQuery(queryNode)) {
            response = await api.query(
                {
                    ...queryNode,
                    teamId: queryNode.teamId ?? getCurrentTeamId(),
                    sessionId: queryNode.sessionId ?? currentSessionId(),
                    sessionStart: queryNode.sessionStart ?? now().subtract(1, 'day').toISOString(),
                    sessionEnd: queryNode.sessionEnd ?? now().toISOString(),
                },
                methodOptions
            )
        } else {
            response = await executeQuery(queryNode, methodOptions, refresh, queryId, setPollResponse)
            if (isHogQLQuery(queryNode) && response && typeof response === 'object') {
                logParams.clickhouse_sql = (response as HogQLQueryResponse)?.clickhouse
            }
        }
        posthog.capture('query completed', { query: queryNode, duration: performance.now() - startTime, ...logParams })
        return response
    } catch (e) {
        posthog.capture('query failed', { query: queryNode, duration: performance.now() - startTime, ...logParams })
        throw e
    }
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

export async function hogqlQuery(queryString: string, values?: Record<string, any>): Promise<HogQLQueryResponse> {
    return await performQuery<HogQLQuery>({
        kind: NodeKind.HogQLQuery,
        query: queryString,
        values,
    })
}
