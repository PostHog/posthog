import { explicitFreshnessLifetimeMs } from './configuration-policy'
import { HttpCacheMetadata } from './crawl-history'
import { parseV4UrlRef } from './v4-native'

/** A reference is fetched again after the crawl history TTL, or later when the response stays fresh for longer. */
export function urlHistoryExpiresAtMs(nowMs: number, seenTtlSeconds: number, cache?: HttpCacheMetadata): number {
    const minimumNextFetchAtMs = nowMs + seenTtlSeconds * 1000
    const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
    return Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
}

/** How long the entry of a reference stays after the end of its month or its last write, as in the v3 lane. */
const GRACE_DAYS = 8

/**
 * When the history entry of a reference may go. A v4 reference carries the month its session started in, and a session
 * can still write after that month ends, so the entry stays 8 days past the later of the month's end and this write.
 * A public font reference has no month, so every team's jobs share its entry until its next fetch.
 */
export function urlHistoryStorageExpiresAtMs(ref: string, nextFetchAtMs: number, nowMs: number): number {
    const v4 = parseV4UrlRef(ref)
    if (!v4 || v4.scope === 'public') {
        return nextFetchAtMs
    }
    const [year, month] = v4.keyMonth.split('-').map(Number)
    const graceMs = GRACE_DAYS * 24 * 60 * 60 * 1000
    return Math.max(Date.UTC(year, month, 1) + graceMs, nowMs + graceMs)
}
