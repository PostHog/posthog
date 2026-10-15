import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { explicitFreshnessLifetimeMs } from './configuration-policy'
import { HttpCacheMetadata } from './crawl-history'

const DAY_MS = 24 * 60 * 60 * 1000
/** A v4 reference is scoped to a team and a day: `imageurl:v4:{team}:{YYYY-MM-DD}:{hash}`. */
const V4_DAY_SCOPED_REF = /^imageurl:v4:\d+:(\d{4}-\d{2}-\d{2}):/

/** The end of day `day + 8`. The v4 lane refuses a reference after its 7-day raw window, so a later entry has no use. */
function v4HistoryExpiresAtMs(ref: string): number | undefined {
    const day = V4_DAY_SCOPED_REF.exec(ref)?.[1]
    const start = day === undefined ? NaN : Date.parse(`${day}T00:00:00Z`)
    return Number.isNaN(start) ? undefined : start + 9 * DAY_MS
}

export function urlHistoryExpiresAtMs(
    ref: string,
    nowMs: number,
    seenTtlSeconds: number,
    cache?: HttpCacheMetadata
): number {
    const v4 = v4HistoryExpiresAtMs(ref)
    if (v4 !== undefined) {
        return v4
    }
    const month = parseImageRef(ref)?.sessionMonth
    if (month !== undefined) {
        // The stored image is write-once per team, month and URL, so a fetch before the month partition ends cannot change it, and HTTP freshness does not shorten this.
        const end = new Date(`${month}-01T00:00:00Z`)
        end.setUTCMonth(end.getUTCMonth() + 1)
        end.setUTCDate(end.getUTCDate() + 8)
        return end.getTime()
    }
    const minimumNextFetchAtMs = nowMs + seenTtlSeconds * 1000
    const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
    return Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
}

export function storedUrlHistoryCache(
    ref: string,
    cache: HttpCacheMetadata | undefined
): HttpCacheMetadata | undefined {
    const isMonthScoped = parseImageRef(ref)?.sessionMonth !== undefined || v4HistoryExpiresAtMs(ref) !== undefined
    const forbidsStoring = /(?:^|,)\s*no-store\s*(?:,|$)/i.test(cache?.cacheControl ?? '')
    return isMonthScoped && forbidsStoring ? undefined : cache
}
