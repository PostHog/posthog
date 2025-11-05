import api, { ApiMethodOptions } from 'lib/api'
import posthog from 'lib/posthog-typed'
import { delay } from 'lib/utils'

import {
    DashboardFilter,
    DataNode,
    HogQLQuery,
    HogQLQueryResponse,
    HogQLVariable,
    NodeKind,
    PersonsNode,
    QueryStatus,
    RefreshType,
} from '~/queries/schema/schema-general'
import { OnlineExportContext, QueryExportContext } from '~/types'

import {
    HogQLQueryString,
    isAsyncResponse,
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryNode,
    isPersonsNode,
    shouldQueryBeAsync,
} from './utils'

const QUERY_ASYNC_MAX_INTERVAL_SECONDS = 3
const QUERY_ASYNC_TOTAL_POLL_SECONDS = 10 * 60 + 6 // keep in sync with backend-side timeout (currently 10min) + a small buffer
export const QUERY_TIMEOUT_ERROR_MESSAGE = 'Query timed out'

//get export context for a given query
export function queryExportContext<N extends DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean
): OnlineExportContext | QueryExportContext {
    if (isDataTableNode(query) || isDataVisualizationNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isInsightQueryNode(query)) {
        return { source: query }
    } else if (isPersonsNode(query)) {
        return { path: getPersonsEndpoint(query) }
    }
    return { source: query }
}

export async function pollForResults(
    queryId: string,
    methodOptions?: ApiMethodOptions,
    onPoll?: (response: QueryStatus) => void
): Promise<QueryStatus> {
    const pollStart = performance.now()
    let currentDelay = 300 // start low, because all queries will take at minimum this

    while (performance.now() - pollStart < QUERY_ASYNC_TOTAL_POLL_SECONDS * 1000) {
        await delay(currentDelay, methodOptions?.signal)
        currentDelay = Math.min(currentDelay * 1.25, QUERY_ASYNC_MAX_INTERVAL_SECONDS * 1000)

        try {
            const statusResponse = (await api.queryStatus.get(queryId, true)).query_status
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
    throw new Error(QUERY_TIMEOUT_ERROR_MESSAGE)
}

/**
 * Execute a query node and return the response, use async query if enabled
 */
async function executeQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: RefreshType,
    queryId?: string,
    setPollResponse?: (response: QueryStatus) => void,
    filtersOverride?: DashboardFilter | null,
    variablesOverride?: Record<string, HogQLVariable> | null,
    /**
     * Whether to limit the function to just polling the provided query ID.
     * This is important in shared contexts, where we cannot create arbitrary queries via POST – we can only GET.
     */
    pollOnly = false
): Promise<NonNullable<N['response']>> {
    if (!pollOnly) {
        // Determine the refresh type based on the query node type and refresh parameter
        let refreshParam: RefreshType

        if (posthog.isFeatureEnabled('always-query-blocking')) {
            refreshParam = refresh || 'blocking'
        } else if (shouldQueryBeAsync(queryNode)) {
            // For insight queries, use async variants but preserve explicit force requests
            refreshParam = refresh || 'async'
        } else {
            // For other queries, use blocking unless explicitly set to a different RefreshType
            refreshParam = refresh || 'blocking'
        }

        const response = await api.query(queryNode, {
            requestOptions: methodOptions,
            clientQueryId: queryId,
            refresh: refreshParam,
            filtersOverride,
            variablesOverride,
        })

        if (response.detail) {
            throw new Error(response.detail)
        }

        if (!isAsyncResponse(response)) {
            // Executed query synchronously or from cache
            return response
        }

        queryId = response.query_status.id
    } else {
        if (refresh !== 'async' && refresh !== 'force_async') {
            throw new Error('pollOnly is only supported for async queries')
        }
        if (!queryId) {
            throw new Error('pollOnly requires a queryId')
        }
    }

    const statusResponse = await pollForResults(queryId, methodOptions, setPollResponse)
    return statusResponse.results
}

// Return data for a given query
export async function performQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: RefreshType,
    queryId?: string,
    setPollResponse?: (status: QueryStatus) => void,
    filtersOverride?: DashboardFilter | null,
    variablesOverride?: Record<string, HogQLVariable> | null,
    pollOnly = false
): Promise<NonNullable<N['response']>> {
    let response: NonNullable<N['response']>
    const logParams: Record<string, any> = {}
    const startTime = performance.now()

    try {
        if (isPersonsNode(queryNode)) {
            response = await api.get(getPersonsEndpoint(queryNode), methodOptions)
        } else {
            response = await executeQuery(
                queryNode,
                methodOptions,
                refresh,
                queryId,
                setPollResponse,
                filtersOverride,
                variablesOverride,
                pollOnly
            )
            if (isHogQLQuery(queryNode) && response && typeof response === 'object') {
                logParams.clickhouse_sql = (response as HogQLQueryResponse)?.clickhouse
            }
        }
        posthog.capture('query completed', {
            query: queryNode,
            queryId,
            duration: performance.now() - startTime,
            is_cached: response?.is_cached,
            ...logParams,
        })
        return response
    } catch (e) {
        posthog.capture('query failed', {
            query: queryNode,
            queryId,
            duration: performance.now() - startTime,
            ...logParams,
        })
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

export async function hogqlQuery(
    queryString: HogQLQueryString,
    values?: Record<string, any>,
    refresh?: RefreshType
): Promise<HogQLQueryResponse> {
    return await performQuery<HogQLQuery>(
        {
            kind: NodeKind.HogQLQuery,
            query: queryString,
            values,
        },
        undefined,
        refresh
    )
}
