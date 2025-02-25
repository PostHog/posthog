import { fetchEventSource } from '@microsoft/fetch-event-source'
import api, { ApiMethodOptions, getCookie } from 'lib/api'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'

import { OnlineExportContext, QueryExportContext } from '~/types'

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
} from './schema'
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
export const QUERY_TIMEOUT_ERROR_MESSAGE = 'Query timed out'

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
] satisfies NodeKind[keyof NodeKind][]

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
    refresh?: boolean,
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
    const isAsyncQuery = methodOptions?.async !== false && !SYNC_ONLY_QUERY_KINDS.includes(queryNode.kind)

    const useOptimizedPolling = posthog.isFeatureEnabled('query-optimized-polling')
    const currentTeamId = teamLogic.findMounted()?.values.currentTeamId

    if (!pollOnly) {
        const refreshParam: RefreshType | undefined =
            refresh && isAsyncQuery ? 'force_async' : isAsyncQuery ? 'async' : refresh

        if (useOptimizedPolling) {
            return new Promise((resolve, reject) => {
                const abortController = new AbortController()

                void fetchEventSource(`/api/environments/${currentTeamId}/query_awaited/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Accept: 'text/event-stream',
                        'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                    },
                    body: JSON.stringify({
                        query: queryNode,
                        client_query_id: queryId,
                        refresh: refreshParam,
                        filters_override: filtersOverride,
                        variables_override: variablesOverride,
                    }),
                    signal: abortController.signal,
                    onmessage(ev) {
                        try {
                            const data = JSON.parse(ev.data)
                            if (data.error) {
                                logQueryEvent('error', data, queryNode)
                                abortController.abort()
                                // Create an error object that matches the API error format
                                const error = {
                                    message: data.error,
                                    status: data.status_code || 500,
                                    detail: data.error_message || data.error,
                                    type: 'network_error',
                                }
                                reject(error)
                            } else if (data.complete === false) {
                                // Progress event - no results yet
                                logQueryEvent('progress', data, queryNode)
                                if (setPollResponse) {
                                    setPollResponse(data)
                                }
                            } else {
                                // Final results
                                logQueryEvent('data', data, queryNode)
                                abortController.abort()
                                resolve(data)
                            }
                        } catch (e) {
                            abortController.abort()
                            reject(e)
                        }
                    },
                    onerror(err) {
                        abortController.abort()
                        reject(err)
                    },
                }).catch(reject)
            })
        }
        const response = await api.query(
            queryNode,
            methodOptions,
            queryId,
            refreshParam,
            filtersOverride,
            variablesOverride
        )

        if (!isAsyncResponse(response)) {
            // Executed query synchronously or from cache
            return response
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

    const statusResponse = await pollForResults(queryId, methodOptions, setPollResponse)
    return statusResponse.results
}

type LogType = 'error' | 'progress' | 'data'

// Logging this as chrome devtools doesn't support showing the event stream for non-native EventSource, but EventSource doesn't support POST requests
/* eslint-disable no-console */
function logQueryEvent(type: LogType, data: any, queryNode: any): void {
    const logConfig = {
        error: {
            title: '⚠️ Query Error',
            titleColor: '#ff0000',
            primaryLog: (data: any) => console.error('Error Details:', data),
            secondaryLog: (queryNode: any) => console.warn('Query Payload:', queryNode),
        },
        progress: {
            title: '🔄 Query Progress',
            titleColor: '#2196f3',
            primaryLog: (data: any) => console.info('Progress Update:', data),
            secondaryLog: (queryNode: any) => console.debug('Query Payload:', queryNode),
        },
        data: {
            title: '✅ Query Result',
            titleColor: '#4caf50',
            primaryLog: (data: any) => console.info('Data:', data),
            secondaryLog: (queryNode: any) => console.debug('Query Payload:', queryNode),
        },
    }

    const config = logConfig[type]
    console.group(`%c${config.title}`, `color: ${config.titleColor}; font-weight: bold; font-size: 12px;`)
    config.primaryLog(data)
    config.secondaryLog(queryNode)
    console.groupEnd()
}
/* eslint-enable no-console */

// Return data for a given query
export async function performQuery<N extends DataNode>(
    queryNode: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean,
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

export async function hogqlQuery(queryString: string, values?: Record<string, any>): Promise<HogQLQueryResponse> {
    return await performQuery<HogQLQuery>({
        kind: NodeKind.HogQLQuery,
        query: queryString,
        values,
    })
}
