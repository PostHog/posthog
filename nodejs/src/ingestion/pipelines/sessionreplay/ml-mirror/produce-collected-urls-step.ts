import { createHash } from 'node:crypto'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import { CollectedUrl } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { ML_IMAGE_FETCH_OUTPUT, MlImageFetchOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

/**
 * The same trade as the image lane's cache, at a much lower cost per entry: a record here holds a
 * digest of the ref and transport URL, with no image bytes or original URL. An entry that this
 * cache drops before its next arrival produces a second time, which costs topic volume and one
 * more ledger read in the fetcher, but never correctness. Time-bucketed keys also make an entry
 * eligible again before crawl history expires, so a mutable URL is recrawled.
 */
const PRODUCED_REF_CACHE_MAX = 500_000
const DEFAULT_PRODUCED_REF_CACHE_WINDOW_MS = 15 * 24 * 60 * 60 * 1000

const MAX_RECORD_BYTES = 512 * 1024

/**
 * The URL count one record may carry. Without it the collector's cap in another crate decides the
 * count, and an increase there makes records the fetcher refuses whole. Keep it below
 * `MAX_URLS_PER_RECORD` in `ml-mirror-image-fetch/collected-urls-record.ts`.
 */
const MAX_RECORD_URLS = 1_000

export interface FrontierJob {
    originalRef: string
    currentUrl: string
    remainingHops: number
    notBeforeMs: number
    firstSeenAtMs: number
    fetchCount: number
    republishCount: number
    lastRepublishReason: null
}

/** One record on the fetch topic. The Kafka key is the registrable domain, so every URL here
 *  belongs to one operator. Hosts can differ within it: a CDN sharding over img1..img8 keeps one
 *  budget but still needs its own robots.txt and connection limit per host. */
export interface CollectedUrlsMessage {
    /**
     * The wire format version. The fetcher reads this topic from another deployment, so the two
     * sides roll separately and a reader needs to know what it is holding.
     */
    v: 2
    jobs: FrontierJob[]
}

function producedUrlCacheKey(entry: CollectedUrl, timeBucket: number): string {
    return createHash('sha256')
        .update(entry.ref)
        .update('\0')
        .update(entry.url)
        .update('\0')
        .update(String(timeBucket))
        .digest('base64url')
}

/**
 * Produce the collected URLs of remote images to the fetch topic, keyed by registrable domain.
 *
 * The URLs of one replay message go into groups by domain, and each group becomes one Kafka
 * message. A Kafka message has one key, so a group holds one domain. A page usually loads its
 * images from one or two operators, so this makes tens of URLs into one or two records.
 *
 * The key is the operator rather than the host, because that is what a rate limit protects. A CDN
 * that shards over img1..img8.cdn.example.com keys to one partition, so one pod holds one budget
 * for it. The anonymizer computes the domain from the public suffix list and sends it with the
 * URL, so this step never repeats that rule.
 *
 * The step does not hold URLs across replay messages. The produce goes back as a pipeline side
 * effect, and the pipeline waits for the side effects of a batch before it commits the offsets of
 * that batch. A buffer that spans messages would break that guarantee, because the pipeline could
 * commit the offset of a message while the URLs of that message were still in the buffer. A crash
 * would then lose them. The group-by-host step already removes most of the record count, `linger.ms`
 * makes the batches on the wire, and the cache stops an identical transport URL before it produces
 * at all. A new transport URL for the same canonical ref still produces.
 *
 * Delivery is not awaited and never fails the message. The mirrored lines already carry the refs
 * in namespaced sibling attributes, while media sources keep their placeholders.
 *
 * The `url` field is the original, unscrubbed URL. It is as sensitive as the raw replay payload, so
 * it goes only into the Kafka value. Log lines and metrics carry hosts and counts only.
 */
export function createProduceCollectedUrlsStep<
    T extends { collectedUrls?: CollectedUrl[]; message: { timestamp?: number } },
>(
    outputs: IngestionOutputs<MlImageFetchOutput>,
    producedRefCacheMax: number = PRODUCED_REF_CACHE_MAX,
    producedRefCacheWindowMs: number = DEFAULT_PRODUCED_REF_CACHE_WINDOW_MS
): ProcessingStep<T, T> {
    if (!Number.isSafeInteger(producedRefCacheWindowMs) || producedRefCacheWindowMs <= 0) {
        throw new Error(`produced URL cache window must be a positive safe integer, got ${producedRefCacheWindowMs}`)
    }
    const producedTransportUrls = new RefDedupCache('image_fetch_producer', producedRefCacheMax)

    return function produceCollectedUrlsStep(input) {
        const collected = input.collectedUrls
        if (!collected?.length) {
            return Promise.resolve(ok(input))
        }

        const timeBucket = Math.floor(Date.now() / producedRefCacheWindowMs)
        const fresh = collected
            .map((entry) => ({ entry, cacheKey: producedUrlCacheKey(entry, timeBucket) }))
            .filter(({ cacheKey }) => !producedTransportUrls.has(cacheKey))
        SessionRecordingIngesterMetrics.incrementMlUrlsCollected('deduped', collected.length - fresh.length)
        if (fresh.length === 0) {
            return Promise.resolve(ok({ ...input, collectedUrls: undefined }))
        }

        // Each entry is checked, not just the first. A `bytes` ref names an image the page
        // inlined, and its hash can never be reproduced from a URL, so a record carrying one
        // reaches the fetcher under a hash nothing will ever match. Both kinds parse, so only
        // `source` separates them, and checking one entry would let every later one through.
        //
        // Every entry must use the global URL-ref shape and carry the same transport pseudonym. One
        // replay message belongs to one team, and a record stamped with another team's pseudonym is
        // a tenant-attribution error that nothing downstream can detect.
        const usable: typeof fresh = []
        let pseudoTeam: string | undefined
        for (const candidate of fresh) {
            const { entry } = candidate
            const parsed = parseImageRef(entry.ref)
            if (
                !parsed ||
                parsed.source !== 'url' ||
                parsed.pseudoTeam !== undefined ||
                (pseudoTeam && entry.pseudoTeam !== pseudoTeam)
            ) {
                continue
            }
            pseudoTeam ??= entry.pseudoTeam
            usable.push(candidate)
        }
        const unusable = fresh.length - usable.length
        if (unusable > 0) {
            SessionRecordingIngesterMetrics.incrementMlUrlsCollected('ref_unusable', unusable)
            // Warn, not error: this is per replay message, so an addon-side format drift would
            // otherwise write an error line at full ingest rate for as long as it lasted.
            logger.warn('🌐', 'ml_image_fetch_ref_unusable', { count: unusable })
        }
        if (!pseudoTeam || usable.length === 0) {
            return Promise.resolve(ok({ ...input, collectedUrls: undefined }))
        }

        const messageTimestamp = input.message.timestamp
        const firstSeenAtMs = messageTimestamp !== undefined && messageTimestamp > 0 ? messageTimestamp : Date.now()
        const byDomain = new Map<string, FrontierJob[]>()
        for (const { entry, cacheKey } of usable) {
            producedTransportUrls.add(cacheKey)
            const group = byDomain.get(entry.domain)
            const record: FrontierJob = {
                originalRef: entry.ref,
                currentUrl: entry.url,
                remainingHops: 10,
                notBeforeMs: 0,
                firstSeenAtMs,
                fetchCount: 0,
                republishCount: 0,
                lastRepublishReason: null,
            }
            SessionRecordingIngesterMetrics.observeMlUrlBytes(Buffer.byteLength(entry.url))
            if (group) {
                group.push(record)
            } else {
                byDomain.set(entry.domain, [record])
            }
        }
        SessionRecordingIngesterMetrics.incrementMlUrlsCollected('queued', usable.length)

        const messages = [...byDomain].flatMap(([domain, jobs]) =>
            packByBytes(jobs, MAX_RECORD_BYTES).map((slice) => {
                const value = Buffer.from(
                    JSON.stringify({
                        v: 2,
                        jobs: slice,
                    } satisfies CollectedUrlsMessage)
                )
                SessionRecordingIngesterMetrics.observeMlUrlRecord(slice.length, value.length)
                return { key: domain, value }
            })
        )

        // The failure handler captures only the cache keys, so that a produce which is not yet
        // delivered does not hold the URL strings alive longer than the messages themselves.
        const producedCacheKeys = usable.map(({ cacheKey }) => cacheKey)
        const produce = outputs
            .queueMessages(ML_IMAGE_FETCH_OUTPUT, messages)
            .then(() => {
                // queueMessages resolves on the delivery acks, so `produced` counts what landed.
                SessionRecordingIngesterMetrics.incrementMlUrlsCollected('produced', producedCacheKeys.length)
            })
            .catch((error) => {
                // A dangling ref renders as a placeholder, so a failed produce is logged and never
                // thrown back into the pipeline. Un-mark the cache entries: the same image in a later
                // snapshot then produces again, one attempt for each recurrence and no retry loop.
                // A duplicate costs the fetcher one ledger read, because the ledger is keyed by ref.
                for (const cacheKey of producedCacheKeys) {
                    producedTransportUrls.delete(cacheKey)
                }
                logger.warn('🌐', 'ml_image_fetch_produce_failed', {
                    count: producedCacheKeys.length,
                    domains: byDomain.size,
                    error: String(error),
                })
                SessionRecordingIngesterMetrics.incrementMlUrlsCollected('produce_failed', producedCacheKeys.length)
            })
        return Promise.resolve(ok({ ...input, collectedUrls: undefined }, [produce]))
    }
}

/**
 * An entry always goes into a record, even alone in one above the budget, because a drop here loses
 * an image that every earlier check accepted. `MAX_URL_LEN` keeps that record under the broker
 * limit.
 */
function packByBytes(entries: FrontierJob[], maxBytes: number): FrontierJob[][] {
    const out: FrontierJob[][] = []
    let current: FrontierJob[] = []
    let bytes = Buffer.byteLength('{"v":2,"jobs":[]}')
    for (const entry of entries) {
        const size = Buffer.byteLength(JSON.stringify(entry)) + (current.length > 0 ? 1 : 0)
        if (current.length > 0 && (bytes + size > maxBytes || current.length >= MAX_RECORD_URLS)) {
            out.push(current)
            current = []
            bytes = Buffer.byteLength('{"v":2,"jobs":[]}')
        }
        current.push(entry)
        bytes += size
    }
    if (current.length > 0) {
        out.push(current)
    }
    return out
}
