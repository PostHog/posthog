import { explicitFreshnessLifetimeMs } from './configuration-policy'
import { HttpCacheMetadata } from './crawl-history'
import { parseV4UrlRef } from './v4-url-ref'

/** A reference is fetched again after the crawl history TTL, or later when the response stays fresh for longer. */
export function urlHistoryExpiresAtMs(nowMs: number, seenTtlSeconds: number, cache?: HttpCacheMetadata): number {
    const minimumNextFetchAtMs = nowMs + seenTtlSeconds * 1000
    const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
    return Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
}

/** How long the entry of a reference stays after the end of its month, as in the v3 lane. */
const MONTH_GRACE_DAYS = 8

/**
 * When the history entry of a reference may go. A v4 reference carries the month it was written in, so the recorder
 * sends no job for it after that month. Its entry stays 8 more days for jobs that are still on their way, and a later
 * job finds no entry and fetches the image again.
 */
export function urlHistoryStorageExpiresAtMs(ref: string, nextFetchAtMs: number): number {
    const v4 = parseV4UrlRef(ref)
    if (!v4) {
        return nextFetchAtMs
    }
    const [year, month] = v4.keyMonth.split('-').map(Number)
    return Date.UTC(year, month, 1 + MONTH_GRACE_DAYS)
}
