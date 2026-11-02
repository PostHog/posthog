import { ApiRequestTiming } from 'lib/apiRequestTiming'

const SLOW_TRANSFER_MIN_TOTAL_MS = 5000
const SLOW_TRANSFER_MIN_SHARE = 0.8
// Below this share, other waits such as status polling or retry backoff filled the rest of the total
const SINGLE_REQUEST_MIN_SHARE = 0.9

export interface QueryTimeBreakdown {
    totalMs: number
    serverMs: number
    transferMs: number
    isTransferSlow: boolean
}

export function getQueryTimeBreakdown(totalMs: number, serverMs: number | null): QueryTimeBreakdown | null {
    if (serverMs === null) {
        return null
    }
    const transferMs = Math.max(totalMs - serverMs, 0)
    return {
        totalMs,
        serverMs,
        transferMs,
        isTransferSlow: totalMs >= SLOW_TRANSFER_MIN_TOTAL_MS && transferMs >= totalMs * SLOW_TRANSFER_MIN_SHARE,
    }
}

/**
 * Server time for a load that was one request with one fetch, so the rest of the total is transfer.
 * Polled, retried and re-authenticated loads include waits the server time cannot explain.
 */
export function getSingleRequestServerMs(timings: ApiRequestTiming[], totalMs: number): number | null {
    if (timings.length !== 1) {
        return null
    }
    const [timing] = timings
    if ((timing.fetch_attempts ?? 1) !== 1 || timing.request_total_ms < totalMs * SINGLE_REQUEST_MIN_SHARE) {
        return null
    }
    return timing.envoy_upstream_ms ?? null
}
