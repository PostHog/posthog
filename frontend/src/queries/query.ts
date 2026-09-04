import api, { ApiMethodOptions, isAbortError } from 'lib/api'
import posthog from 'lib/posthog-typed'
import { delay } from 'lib/utils/async'
import { uuid } from 'lib/utils/dom'

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
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { OnlineExportContext, QueryExportContext } from '~/types'

import {
    dataWarehouseSourcesFromResponse,
    HogQLQueryString,
    isAsyncResponse,
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryNode,
    isPersonsNode,
    queryUsesDataWarehouse,
} from './utils'

export function waitForPageVisible(signal?: AbortSignal): Promise<void> {
    if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        return Promise.resolve()
    }

    return new Promise<void>((resolve, reject) => {
        const onVisibilityChange = (): void => {
            if (document.visibilityState === 'visible') {
                cleanup()
                resolve()
            }
        }

        const onAbort = (): void => {
            cleanup()
            reject(new DOMException('Aborted', 'AbortError'))
        }

        const cleanup = (): void => {
            document.removeEventListener('visibilitychange', onVisibilityChange)
            signal?.removeEventListener('abort', onAbort)
        }

        if (signal?.aborted) {
            reject(new DOMException('Aborted', 'AbortError'))
            return
        }

        document.addEventListener('visibilitychange', onVisibilityChange)
        signal?.addEventListener('abort', onAbort)
    })
}

const QUERY_ASYNC_MAX_INTERVAL_SECONDS = 3
const QUERY_ASYNC_TOTAL_POLL_SECONDS = 10 * 60 + 6 // keep in sync with backend-side timeout (currently 10min) + a small buffer
export const QUERY_TIMEOUT_ERROR_MESSAGE = 'Query timed out'

// The server keeps running a query after the ingress drops the request, then records the outcome
// under the client's query ID. Give it longer than a blocking query is allowed to run, and stay
// inside the record's lifetime (BLOCKING_QUERY_STATUS_TTL_SECONDS, 15 minutes).
const DROPPED_REQUEST_RECOVERY_DEADLINE_MS = 10 * 60 * 1000
const DROPPED_REQUEST_RECOVERY_POLL_INTERVAL_MS = 5_000

/** What the dropped-request recovery did for one request, reported on the query telemetry events. */
export interface QueryRecoveryOutcome {
    attempted: boolean
    recovered: boolean
    waitMs: number
}

/**
 * The gateway gave up waiting for a response it had already accepted, so the server may still be
 * running the query. A 502 or 503 means the request never reached a worker, and waiting on those
 * would only add minutes of silence to an error the user should see now.
 */
function isDroppedRequest(error: unknown): boolean {
    return (error as { status?: number } | null)?.status === 504
}

function blocksOnServer(refresh: RefreshType | undefined): boolean {
    return refresh !== 'async' && refresh !== 'force_async' && refresh !== 'lazy_async' && refresh !== 'force_cache'
}

/**
 * Poll the status of a query whose blocking request was dropped. Resolves with the recorded result,
 * rejects with the recorded error, and returns null when nothing was recorded before the deadline.
 * A 404 means the server has not finished the query yet, or has already forgotten it.
 */
async function waitForRecordedResult(
    queryId: string,
    methodOptions: ApiMethodOptions | undefined,
    requestStartedAtMs: number
): Promise<QueryStatus | null> {
    const untilMs = requestStartedAtMs + DROPPED_REQUEST_RECOVERY_DEADLINE_MS
    for (;;) {
        try {
            const statusResponse = (await api.queryStatus.get(queryId, false)).query_status
            if (statusResponse.complete) {
                return statusResponse
            }
        } catch (e: any) {
            if (isAbortError(e)) {
                throw e
            }
            const expired = e?.data?.code === 'query_result_expired'
            if (e?.status !== 404 || expired) {
                const parsed = parseErrorMessage(e.data?.query_status?.error_message ?? e.data?.detail ?? e.detail)
                e.detail = parsed.message
                e.code = e.data?.query_status?.error_code ?? e.data?.code ?? parsed.code ?? e.code
                e.queryId = queryId
                throw e
            }
        }
        const remainingMs = untilMs - Date.now()
        if (remainingMs <= 0) {
            return null
        }
        await delay(Math.min(DROPPED_REQUEST_RECOVERY_POLL_INTERVAL_MS, remainingMs), methodOptions?.signal)
    }
}

/**
 * Parse error message that may be in ErrorDetail string format.
 * Backend sometimes serializes ValidationError.detail as a string like:
 * "[ErrorDetail(string='Message', code='code')]"
 *
 * This function safely extracts the message and code, falling back to the
 * original string if parsing fails.
 */
export function parseErrorMessage(errorMessage: string | undefined): { message: string; code: string | null } {
    if (!errorMessage || typeof errorMessage !== 'string') {
        return { message: errorMessage || '', code: null }
    }

    // Try to match list format: [ErrorDetail(string='...', code='...')]
    const listMatch = errorMessage.match(/\[ErrorDetail\(string='([^']*)',\s*code='([^']*)'\)\]/)
    if (listMatch) {
        return { message: listMatch[1], code: listMatch[2] }
    }

    // Try to match single format: ErrorDetail(string='...', code='...')
    const singleMatch = errorMessage.match(/ErrorDetail\(string='([^']*)',\s*code='([^']*)'\)/)
    if (singleMatch) {
        return { message: singleMatch[1], code: singleMatch[2] }
    }

    // Fallback: return original string unchanged
    return { message: errorMessage, code: null }
}

//get export context for a given query
export function queryExportContext<N extends DataNode>(
    query: N,
    methodOptions?: ApiMethodOptions,
    refresh?: boolean
): OnlineExportContext | QueryExportContext {
    if (isDataTableNode(query) || isDataVisualizationNode(query)) {
        return queryExportContext(query.source, methodOptions, refresh)
    } else if (isInsightQueryNode(query)) {
        return {
            source: query,
        }
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
    // Measured only across time spent actually polling (page visible), not raw wall-clock time -
    // otherwise a backgrounded tab burns down the deadline via waitForPageVisible below without
    // ever getting a chance to poll, and the query "times out" despite never really being tried.
    let activeElapsedMs = 0
    let currentDelay = 300 // start low, because all queries will take at minimum this

    while (activeElapsedMs < QUERY_ASYNC_TOTAL_POLL_SECONDS * 1000) {
        await waitForPageVisible(methodOptions?.signal)
        const iterationStart = performance.now()
        await delay(currentDelay, methodOptions?.signal)
        currentDelay = Math.min(currentDelay * 1.25, QUERY_ASYNC_MAX_INTERVAL_SECONDS * 1000)
        activeElapsedMs += performance.now() - iterationStart

        try {
            const statusResponse = (await api.queryStatus.get(queryId, true)).query_status
            if (statusResponse.complete) {
                return statusResponse
            }
            if (onPoll) {
                onPoll(statusResponse)
            }
        } catch (e: any) {
            // Parse error message to extract clean message and code if present
            const parsed = parseErrorMessage(e.data?.query_status?.error_message ?? e.data?.detail ?? e.detail)
            e.detail = parsed.message

            // Prefer the structured code from QueryStatus over one parsed out of the message
            e.code = e.data?.query_status?.error_code ?? e.data?.code ?? parsed.code ?? e.code

            // Attach queryId to error for downstream error handling
            e.queryId = queryId

            throw e
        }
    }

    // if we get here, the query timed out
    const timeoutError = new Error(QUERY_TIMEOUT_ERROR_MESSAGE)
    ;(timeoutError as Error & { queryId?: string }).queryId = queryId
    throw timeoutError
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
    pollOnly = false,
    limitContext?: 'posthog_ai',
    /**
     * When the backend serves a cached result while kicking off a background recompute
     * (stale-while-revalidate: `is_cached` is true *and* an incomplete `query_status` is
     * attached), return the cached results immediately instead of blocking on the recompute.
     */
    acceptStaleCache = false,
    /**
     * Filled in when the gateway gave up on a blocking request while the server kept running the
     * query. The server records the outcome under the client query ID, so this call polls that ID
     * and returns the result instead of the gateway error. Absent for poll-only callers, which
     * cannot send queries.
     */
    recovery?: QueryRecoveryOutcome
): Promise<NonNullable<N['response']>> {
    const requestStartedAtMs = Date.now()
    if (!pollOnly) {
        const refreshParam: RefreshType = refresh || 'blocking'
        // Every blocking request carries an ID the server records its outcome under, so a
        // dropped request can be followed up on. Async requests get their ID from the response.
        if (!queryId && blocksOnServer(refreshParam)) {
            queryId = uuid()
        }

        let response: any
        try {
            response = await api.query(queryNode, {
                requestOptions: methodOptions,
                clientQueryId: queryId,
                refresh: refreshParam,
                filtersOverride,
                variablesOverride,
                limitContext,
            })
        } catch (e: any) {
            if (!recovery || !queryId || !blocksOnServer(refreshParam) || !isDroppedRequest(e)) {
                throw e
            }
            const droppedAtMs = Date.now()
            recovery.attempted = true
            const recorded = await waitForRecordedResult(queryId, methodOptions, requestStartedAtMs)
            if (!recorded) {
                throw e
            }
            recovery.recovered = true
            recovery.waitMs = Date.now() - droppedAtMs
            return recorded.results
        }

        if (response.detail) {
            throw new Error(response.detail)
        }

        if (!isAsyncResponse(response)) {
            // Executed query synchronously or from cache
            return response
        }

        if (acceptStaleCache && 'is_cached' in response && response.is_cached) {
            // Cached results are already present alongside a background recompute, so use them
            // now rather than discarding them to poll a job that may take a while (or be stuck).
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
    pollOnly = false,
    limitContext?: 'posthog_ai',
    acceptStaleCache = false
): Promise<NonNullable<N['response']>> {
    let response: NonNullable<N['response']>
    const logParams: Record<string, any> = {}
    const startTime = performance.now()
    const recovery: QueryRecoveryOutcome = { attempted: false, recovered: false, waitMs: 0 }

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
                pollOnly,
                limitContext,
                acceptStaleCache,
                pollOnly ? undefined : recovery
            )
            if (recovery.recovered) {
                logParams.recovered_after_drop = true
                logParams.recovery_wait_ms = Math.round(recovery.waitMs)
            }
            if (isHogQLQuery(queryNode) && response && typeof response === 'object') {
                logParams.clickhouse_sql = (response as HogQLQueryResponse)?.clickhouse
            }
            if (response && typeof response === 'object') {
                // Web analytics responses report which read path served them, whether a
                // lazy-precompute read was served stale, and why a live read skipped precompute.
                // Undefined elsewhere, so these props only land on events that carry them. The
                // shape comes from the generated schema, so renaming a field there fails the
                // build instead of silently capturing undefined.
                const { preComputeStrategy, preComputeStale, preComputeIneligibleReason } = response as Partial<
                    Pick<
                        WebStatsTableQueryResponse,
                        'preComputeStrategy' | 'preComputeStale' | 'preComputeIneligibleReason'
                    >
                >
                logParams.precompute_strategy = preComputeStrategy
                logParams.precompute_stale = preComputeStale
                logParams.precompute_ineligible_reason = preComputeIneligibleReason
            }
        }
        const warehouseSources = dataWarehouseSourcesFromResponse(response)
        posthog.capture('query completed', {
            query: queryNode,
            queryId,
            duration: performance.now() - startTime,
            is_cached: response?.is_cached,
            uses_data_warehouse_source: warehouseSources.length > 0 || queryUsesDataWarehouse(queryNode),
            data_warehouse_source_ids: warehouseSources.map((s) => s.id),
            data_warehouse_source_types: warehouseSources.map((s) => s.source_type).filter(Boolean),
            ...logParams,
        })
        return response
    } catch (e) {
        // A superseded query or navigating away mid-request aborts, not fails — skip so the
        // 'query failed' metric isn't drowned in cancellation noise.
        if (!isAbortError(e)) {
            // Raw error detail/message can echo query fragments, so telemetry only gets status and code
            const error = e as (Error & { status?: number; code?: string | null }) | null
            posthog.capture('query failed', {
                query: queryNode,
                queryId,
                duration: performance.now() - startTime,
                error_status: error?.status ?? null,
                error_code: error?.code ?? null,
                uses_data_warehouse_source: queryUsesDataWarehouse(queryNode),
                drop_recovery_attempted: recovery.attempted,
                ...logParams,
            })
        }
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
