import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { explicitFreshnessLifetimeMs } from './configuration-policy'
import { HttpCacheMetadata } from './crawl-history'

export function urlHistoryExpiresAtMs(
    ref: string,
    nowMs: number,
    seenTtlSeconds: number,
    cache?: HttpCacheMetadata
): number {
    const minimumNextFetchAtMs = nowMs + seenTtlSeconds * 1000
    const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
    const month = parseImageRef(ref)?.sessionMonth
    const partitionExpiresAtMs = month ? Date.parse(`${month}-01T00:00:00Z`) : undefined
    let nextFetchAtMs = Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
    if (partitionExpiresAtMs !== undefined) {
        const end = new Date(partitionExpiresAtMs)
        end.setUTCMonth(end.getUTCMonth() + 1)
        end.setUTCDate(end.getUTCDate() + 8)
        const hasExplicitFreshness =
            cache?.expires !== undefined ||
            /(?:^|,)\s*(?:s-maxage|max-age|no-cache|no-store|private|must-revalidate)(?:\s*(?:=|,|$))/i.test(
                cache?.cacheControl ?? ''
            )
        nextFetchAtMs = Math.min(end.getTime(), hasExplicitFreshness ? explicitNextFetchAtMs : Infinity)
    }
    return nextFetchAtMs
}
