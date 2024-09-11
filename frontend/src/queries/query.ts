import api, { ApiMethodOptions } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'

import { OnlineExportContext, QueryExportContext } from '~/types'

import { DataNode, HogQLQuery, HogQLQueryResponse, NodeKind, PersonsNode, QueryStatus } from './schema'
import {
    isAsyncResponse,
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightVizNode,
    isPersonsNode,
} from './utils'

const QUERY_ASYNC_MAX_INTERVAL_SECONDS = 3
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
    }
    return { source: query }
}

const SYNC_ONLY_QUERY_KINDS = [
    'HogQuery',
    'HogQLMetadata',
    'HogQLAutocomplete',
    'DatabaseSchemaQuery',
    'ErrorTrackingQuery',
] satisfies NodeKind[keyof NodeKind][]

export async function pollForResults(
    queryId: string,
    showProgress: boolean,
    methodOptions?: ApiMethodOptions,
    onPoll?: (response: QueryStatus) => void
): Promise<QueryStatus> {
    const pollStart = performance.now()
    let currentDelay = 300 // start low, because all queries will take at minimum this

    while (performance.now() - pollStart < QUERY_ASYNC_TOTAL_POLL_SECONDS * 1000) {
        await delay(currentDelay, methodOptions?.signal)
        currentDelay = Math.min(currentDelay * 1.25, QUERY_ASYNC_MAX_INTERVAL_SECONDS * 1000)

        try {
            const statusResponse = (await api.queryStatus.get(queryId, showProgress)).query_status
            if (statusResponse.complete) {
                return statusResponse
            }
            if (onPoll) {
                onPoll(statusResponse)
            }
        } catch (e: any) {
            e.detail = e.data?.query_status?.error_message
            throw e
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
    setPollResponse?: (response: QueryStatus) => void,
    /**
     * Whether to limit the function to just polling the provided query ID.
     * This is important in shared contexts, where we cannot create arbitrary queries via POST – we can only GET.
     */
    pollOnly = false
): Promise<NonNullable<N['response']>> {
    const isAsyncQuery =
        methodOptions?.async !== false &&
        !SYNC_ONLY_QUERY_KINDS.includes(queryNode.kind) &&
        !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.QUERY_ASYNC]
    const showProgress = !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.INSIGHT_LOADING_BAR]

    if (!pollOnly) {
        const response = await api.query(queryNode, methodOptions, queryId, refresh, isAsyncQuery)

        if (!isAsyncResponse(response)) {
            // Executed query synchronously or from cache
            return response
        }

        if (response.query_status.complete) {
            // Async query returned immediately
            return response.results
        }

        queryId = response.query_status.id
    } else {
        if (!isAsyncQuery) {
            throw new Error('pollOnly is only supported for async queries')
        }
        if (!queryId) {
            throw new Error('pollOnly requires a queryId')
        }
    }
    const statusResponse = await pollForResults(queryId, showProgress, methodOptions, setPollResponse)
    return statusResponse.results
}

// Return data for a given query
export async function performQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
    queryId?: string,
    setPollResponse?: (status: QueryStatus) => void,
    pollOnly = false
): Promise<NonNullable<N['response']>> {
    let response: NonNullable<N['response']>
    const logParams: Record<string, any> = {}
    const startTime = performance.now()

    try {
        if (isPersonsNode(queryNode)) {
            response = await api.get(getPersonsEndpoint(queryNode), methodOptions)
        } else {
            response = await executeQuery(queryNode, methodOptions, refresh, queryId, setPollResponse, pollOnly)
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
