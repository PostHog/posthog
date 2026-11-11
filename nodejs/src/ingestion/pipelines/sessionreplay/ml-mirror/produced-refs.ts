import type { ProducedRefDedup, RefDedupCache } from '@posthog/replay-anonymizer'

import { registerNativeRefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { getRustAnonymizer } from './rust-anonymizer'

function nativeRefDedupCache(name: string, max: number): RefDedupCache {
    const cache = new (getRustAnonymizer().RefDedupCache)(max)
    registerNativeRefDedupCache(name, max, () => cache.stats())
    return cache
}

/**
 * The image refs this process already produced to the scrub topic.
 *
 * The Rust collector only dedups within one message, leaving this as the sole thing between a hot
 * sprite and one produce per recurrence, so capacity translates directly into scrub-topic volume: a
 * ref evicted before its next sighting is re-produced and re-scrubbed. Overflowing it costs topic
 * bytes rather than correctness, since the consumer dedupes by ref too.
 */
export class ProducedImageRefs {
    readonly cache: RefDedupCache

    constructor(max: number) {
        this.cache = nativeRefDedupCache('image_scrub_producer', max)
    }

    claim(refs: string[]): boolean[] {
        return this.cache.claimRefs(refs)
    }

    release(refs: string[]): void {
        this.cache.releaseRefs(refs)
    }
}

export interface TransportUrl {
    ref: string
    url: string
}

/**
 * The transport URLs this process already produced to the fetch topic. An entry that this cache
 * drops before its next arrival produces a second time, which costs topic volume and one more
 * ledger read in the fetcher, but never correctness. Time-bucketed keys also make an entry
 * eligible again before crawl history expires, so a mutable URL is recrawled.
 */
export class ProducedTransportUrls {
    readonly cache: RefDedupCache

    constructor(
        max: number,
        private readonly windowMs: number
    ) {
        if (!Number.isSafeInteger(windowMs) || windowMs <= 0) {
            throw new Error(`produced URL cache window must be a positive safe integer, got ${windowMs}`)
        }
        this.cache = nativeRefDedupCache('image_fetch_producer', max)
    }

    timeBucket(nowMs: number): number {
        return Math.floor(nowMs / this.windowMs)
    }

    claim(urls: TransportUrl[], nowMs: number): boolean[] {
        return this.cache.claimTransportUrls(
            urls.map(({ ref }) => ref),
            urls.map(({ url }) => url),
            this.timeBucket(nowMs)
        )
    }

    /** `nowMs` must be the value the claim used, so the release finds the same time bucket. */
    release(urls: TransportUrl[], nowMs: number): void {
        this.cache.releaseTransportUrls(
            urls.map(({ ref }) => ref),
            urls.map(({ url }) => url),
            this.timeBucket(nowMs)
        )
    }
}

export interface ProducedRefs {
    images?: ProducedImageRefs
    urls?: ProducedTransportUrls
}

export function producedRefDedup(producedRefs: ProducedRefs | undefined, nowMs: number): ProducedRefDedup | undefined {
    if (!producedRefs?.images && !producedRefs?.urls) {
        return undefined
    }
    return {
        images: producedRefs.images?.cache,
        urls: producedRefs.urls?.cache,
        urlTimeBucket: producedRefs.urls?.timeBucket(nowMs),
    }
}
