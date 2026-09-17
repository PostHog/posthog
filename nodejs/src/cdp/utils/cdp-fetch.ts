import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { fetchAttribution } from '~/common/utils/fetch-attribution'
import { logger } from '~/common/utils/logger'
import { FetchOptions, FetchResponse, InvalidRequestError, SecureRequestError, fetch } from '~/common/utils/request'
import { tryCatch } from '~/common/utils/try-catch'

import { PluginsServerConfig } from '../../types'

export const MAX_FETCH_TIMEOUT_MS = 10000

/** Narrowed config type for CDP fetch retry settings, used by native/segment destination executors */
export type CdpFetchConfig = Pick<
    PluginsServerConfig,
    'CDP_FETCH_RETRIES' | 'CDP_FETCH_BACKOFF_BASE_MS' | 'CDP_FETCH_BACKOFF_MAX_MS'
>

const cdpHttpRequests = new Counter({
    name: 'cdp_http_requests',
    help: 'HTTP requests and their outcomes',
    labelNames: ['status', 'template_id'],
})

const cdpHttpRequestTiming = new Histogram({
    name: 'cdp_http_request_timing_ms',
    help: 'Timing of HTTP requests',
    buckets: [0, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 10000],
})

const cdpHttpRequestTimingRetried = new Histogram({
    name: 'cdp_http_request_timing_retried_ms',
    help: 'Timing of HTTP requests that required immediate retry after a connection-level error',
    buckets: [0, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 10000],
})

// SecureRequestError (private/link-local IP), ResolutionError (DNS failed or every
// resolved IP was unsafe) and InvalidRequestError (bad scheme/URL) all mean the request
// was refused before or during connection — never a response from the destination.
// Matched by name, not instanceof: tests that mock ~/common/utils/request leave the
// error classes undefined, and instanceof against undefined throws.
export function isBlockedRequestError(error: unknown): boolean {
    const name = (error as { name?: string } | null)?.name
    return name === 'SecureRequestError' || name === 'ResolutionError' || name === 'InvalidRequestError'
}

// Emit ops-visible attribution for a blocked request. The low-level guard in
// common/utils/request.ts increments `node_request_unsafe` but has no team/function context,
// and the customer-facing `addLog` entries are team-scoped and not queryable from the ops
// side — this log carries the attribution needed to trace a block back to a destination.
function logBlockedRequest(
    error: Error,
    { url, templateId, teamId, hogFunctionId }: CdpFetchAttribution & { url: string; templateId: string }
): void {
    let hostname: string | undefined
    try {
        hostname = new URL(url).hostname
    } catch {
        // Malformed URL (InvalidRequestError) — hostname stays undefined
    }
    logger.warn('[cdpTrackedFetch] Request blocked by SSRF / URL-validation guard', {
        reason: error.name,
        message: error.message,
        hostname,
        teamId,
        hogFunctionId,
        templateId,
    })
}

// Stale keep-alive connections produce these errors when the server has closed its end before
// we reuse the socket. A single in-process retry on a fresh connection may resolve them immediately.
export function isConnectionLevelError(error: any): boolean {
    return (
        error?.code === 'UND_ERR_SOCKET' || // undici SocketError ("other side closed")
        error?.code === 'ECONNRESET' ||
        error?.code === 'EPIPE' ||
        error?.message === 'other side closed' ||
        error?.message === 'socket hang up'
    )
}

// An AggregateError's own message is usually empty — undici throws it when every connection
// attempt to a host fails, and the per-address reasons (ECONNREFUSED, ETIMEDOUT, ...) live in
// `errors`. Without unpacking them, the customer-facing log reads "AggregateError: " with no way
// to tell a DNS failure from a refused connection.
export function fetchErrorDetail(error: Error): string {
    const causes =
        error instanceof AggregateError && error.errors.length > 0
            ? error.errors.map((e) => (e instanceof Error ? e.message : String(e))).join('; ')
            : ''
    if (error.message && causes) {
        return `${error.message} (${causes})`
    }
    return error.message || causes
}

// Attribution for a tracked fetch, so a blocked/refused request can be traced back to the
// owning hog function and team. Optional because a few callers (push notifications, hog
// transformations) hand `cdpTrackedFetch` to the Hog VM without an invocation in scope.
export type CdpFetchAttribution = {
    teamId?: number
    hogFunctionId?: string
}

export async function cdpTrackedFetch({
    url,
    fetchParams,
    templateId,
    teamId,
    hogFunctionId,
}: {
    url: string
    fetchParams: FetchOptions
    templateId: string
} & CdpFetchAttribution): Promise<{
    fetchError: Error | null
    fetchResponse: FetchResponse | null
    fetchDuration: number
}> {
    const start = performance.now()

    // Attribution read by the URL-validation check logs in common/utils/request.ts, which
    // run inside undici's connect flow where no caller context is otherwise available.
    const doFetch = () =>
        fetchAttribution.run({ teamId, hogFunctionId, templateId }, () =>
            tryCatch(async () => await fetch(url, fetchParams))
        )

    let [fetchError, fetchResponse] = await doFetch()

    const fetchDuration = performance.now() - start
    cdpHttpRequestTiming.observe(fetchDuration)
    cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error', template_id: templateId })

    if (fetchError && isConnectionLevelError(fetchError)) {
        logger.warn('🦔', '[cdpTrackedFetch] Connection-level error detected, immediately retrying fetch once', {
            url,
            error: fetchError,
        })
        ;[fetchError, fetchResponse] = await doFetch()
        const retryDuration = performance.now() - start
        cdpHttpRequestTimingRetried.observe(retryDuration)
        cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error', template_id: templateId })
        if (fetchError && isBlockedRequestError(fetchError)) {
            logBlockedRequest(fetchError, { url, templateId, teamId, hogFunctionId })
        }
        return { fetchError, fetchResponse, fetchDuration: retryDuration }
    }

    if (fetchError && isBlockedRequestError(fetchError)) {
        logBlockedRequest(fetchError, { url, templateId, teamId, hogFunctionId })
    }

    return { fetchError, fetchResponse, fetchDuration }
}

export const RETRIABLE_STATUS_CODES = [
    408, // Request Timeout
    429, // Too Many Requests (rate limiting)
    500, // Internal Server Error
    502, // Bad Gateway
    503, // Service Unavailable
    504, // Gateway Timeout
]

export const isFetchResponseRetriable = (response: FetchResponse | null, error: any | null): boolean => {
    let canRetry = !!response?.status && RETRIABLE_STATUS_CODES.includes(response.status)

    if (error) {
        if (
            error instanceof SecureRequestError ||
            error instanceof InvalidRequestError ||
            error.name === 'ResponseContentLengthMismatchError'
        ) {
            canRetry = false
        } else {
            canRetry = true // Only retry on general errors, not security, validation, or response parsing errors
        }
    }

    return canRetry
}

export const getNextRetryTime = (backoffBaseMs: number, backoffMaxMs: number, tries: number): DateTime => {
    const backoffMs = Math.min(backoffBaseMs * tries + Math.floor(Math.random() * backoffBaseMs), backoffMaxMs)
    return DateTime.utc().plus({ milliseconds: backoffMs })
}
