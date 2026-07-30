import { QUERY_TIMEOUT_ERROR_MESSAGE } from '~/queries/query'

/**
 * Delay before each automatic retry, in order. The length of this list caps how many retries
 * we attempt, so widening it directly multiplies the load a persistently failing tile puts on
 * the query backend.
 */
export const AUTO_RETRY_DELAYS_MS = [2000, 6000]

/** Statuses where the same query has a real chance of succeeding on a second attempt. */
const TRANSIENT_HTTP_STATUSES = new Set([0, 429, 500, 502, 503, 504])

/**
 * Whether a failed query looks transient (capacity, a dropped connection, a poll that never
 * completed) rather than a problem with the query itself. Retrying a query that is invalid, too
 * expensive, or forbidden just burns backend capacity and delays the error the user needs to see.
 */
export function isTransientQueryFailure(errorObject: Record<string, any> | null | undefined): boolean {
    if (!errorObject) {
        return false
    }

    // A validation error means the query as written cannot succeed, no matter how often we send it
    if (errorObject.type === 'validation_error' || errorObject.code) {
        return false
    }

    if (typeof errorObject.status === 'number') {
        return TRANSIENT_HTTP_STATUSES.has(errorObject.status)
    }

    // The async poll giving up has no status — it's a plain Error raised client-side
    return errorObject.message === QUERY_TIMEOUT_ERROR_MESSAGE
}
