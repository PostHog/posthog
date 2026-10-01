import type { CollectedUrlBatch, UrlRecords } from '@posthog/replay-anonymizer'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { logger } from '~/common/utils/logger'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import type { CrawlHistoryStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { ML_IMAGE_FETCH_OUTPUT, MlImageFetchOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlSessionKeys } from './keys/key-store'
import { mlKafkaHeaders, mlWireVersion, validateImageOwner } from './keys/transport'
import { MlMirrorMetrics } from './metrics'
import { ProducedTransportUrls } from './produced-refs'
import { usesRawSessionIdentifiers } from './session-identifier-format'

const MAX_RECORD_BYTES = 512 * 1024
const TOP_REGISTRABLE_DOMAINS = 10
const MAX_TRACKED_REGISTRABLE_DOMAINS = 1_000
const CRAWL_HISTORY_WARNING_INTERVAL_MS = 60_000

/**
 * The URL count one record may carry. Without it the collector's cap in another crate decides the
 * count, and an increase there makes records the fetcher refuses whole. Keep it below
 * `MAX_JOBS_PER_RECORD` in `ml-mirror-image-fetch/collected-urls-record.ts`.
 */
const MAX_RECORD_URLS = 1_000

export interface FrontierJob {
    sessionId?: string
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

export interface ProduceCollectedUrlsOptions {
    crawlHistory?: Pick<CrawlHistoryStore, 'read'>
}

interface CrawlHistoryPrecheck {
    excludedRefs: string[]
    succeeded: boolean
}

async function readCrawlHistory(
    batch: CollectedUrlBatch,
    claimedCount: number,
    crawlHistory: Pick<CrawlHistoryStore, 'read'>,
    nowMs: number,
    onError: (error: unknown, count: number) => void
): Promise<CrawlHistoryPrecheck> {
    const startedAt = performance.now()
    try {
        const refs = batch.uniqueRefs()
        const stored = await crawlHistory.read(refs)
        const excludedRefs = refs.filter((ref) => {
            const history = stored.get(ref)
            return history?.kind === 'url' && history.nextFetchAtMs > nowMs
        })
        MlMirrorMetrics.observeMlUrlCrawlHistoryDuration('success', (performance.now() - startedAt) / 1000)
        return { excludedRefs, succeeded: true }
    } catch (error) {
        MlMirrorMetrics.incrementMlUrlCrawlHistory('error', claimedCount)
        MlMirrorMetrics.observeMlUrlCrawlHistoryDuration('error', (performance.now() - startedAt) / 1000)
        onError(error, claimedCount)
        return { excludedRefs: [], succeeded: false }
    }
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
 * The `currentUrl` of a job is the original, unscrubbed URL. It is as sensitive as the raw replay payload, so
 * it goes only into the Kafka value. Log lines and metrics carry hosts and counts only.
 */
export function createProduceCollectedUrlsStep<
    T extends {
        team?: { teamId: number }
        headers?: { session_id: string }
        collectedUrls?: CollectedUrlBatch
        message: { timestamp?: number }
        mlKeys?: MlSessionKeys
    },
>(
    outputs: IngestionOutputs<MlImageFetchOutput>,
    topHog: TopHogRegistry,
    producedUrls: ProducedTransportUrls,
    options: ProduceCollectedUrlsOptions = {}
): ProcessingStep<T, T> {
    const { crawlHistory } = options
    const producedUrlsByRegistrableDomain = topHog.registerSum('ml_image_fetch_produced_urls_by_registrable_domain', {
        topN: TOP_REGISTRABLE_DOMAINS,
        maxKeys: MAX_TRACKED_REGISTRABLE_DOMAINS,
    })
    const producedUrlsTotal = topHog.registerSum('ml_image_fetch_produced_urls_total', { topN: 1, maxKeys: 1 })
    let nextCrawlHistoryWarningAtMs = 0

    return async function produceCollectedUrlsStep(input) {
        const sessionId = input.headers?.session_id
        const key = sessionId && usesRawSessionIdentifiers(sessionId) ? input.mlKeys?.session : undefined
        const batch = input.collectedUrls
        if (!batch) {
            return ok(input)
        }

        // A ref of another shape, such as a `bytes` ref, reaches the fetcher under a hash that nothing
        // will ever match.
        validateImageOwner(batch.firstRef, key)
        const parsed = parseImageRef(batch.firstRef)
        if (!parsed || parsed.source !== 'url' || parsed.pseudoTeam !== undefined) {
            MlMirrorMetrics.incrementMlUrlsCollected('ref_unusable', batch.count)
            // Warn, not error: this is per replay message, so an addon-side format drift would
            // otherwise write an error line at full ingest rate for as long as it lasted.
            logger.warn('🌐', 'ml_image_fetch_ref_unusable', { count: batch.count })
            return ok({ ...input, collectedUrls: undefined })
        }

        const nowMs = Date.now()
        const claimedCount = batch.claim(producedUrls.cache, producedUrls.timeBucket(nowMs))
        MlMirrorMetrics.incrementMlUrlsCollected('deduped', batch.count - claimedCount)
        if (claimedCount === 0) {
            return ok({ ...input, collectedUrls: undefined })
        }

        const precheck = crawlHistory
            ? await readCrawlHistory(batch, claimedCount, crawlHistory, nowMs, (error, count) => {
                  if (nowMs < nextCrawlHistoryWarningAtMs) {
                      return
                  }
                  nextCrawlHistoryWarningAtMs = nowMs + CRAWL_HISTORY_WARNING_INTERVAL_MS
                  logger.warn('🌐', 'ml_image_fetch_crawl_history_precheck_failed', { count, error: String(error) })
              })
            : undefined

        const messageTimestamp = input.message.timestamp
        const firstSeenAtMs =
            messageTimestamp !== undefined && Number.isSafeInteger(messageTimestamp) && messageTimestamp > 0
                ? messageTimestamp
                : nowMs
        const records = batch.buildRecords({
            excludedRefs: precheck?.excludedRefs ?? [],
            sessionId: key && sessionId ? sessionId : null,
            firstSeenAtMs,
            maxRecordBytes: MAX_RECORD_BYTES,
            maxRecordUrls: MAX_RECORD_URLS,
        })
        const publishedCount = records.urlByteLengths.length
        if (precheck?.succeeded) {
            MlMirrorMetrics.incrementMlUrlCrawlHistory('fresh', claimedCount - publishedCount)
            MlMirrorMetrics.incrementMlUrlCrawlHistory('miss', publishedCount)
        }
        if (publishedCount === 0) {
            return ok({ ...input, collectedUrls: undefined })
        }

        MlMirrorMetrics.observeMlUrlBytes(records.urlByteLengths)
        MlMirrorMetrics.incrementMlUrlsCollected('queued', publishedCount)
        const messages = fetchTopicMessages(records, {
            [CAPTURE_TIMESTAMP_HEADER]: String(firstSeenAtMs),
            ...mlKafkaHeaders(mlWireVersion(key)),
        })

        // The fetch consumer counts records, so the producer counts records too and the two rates compare.
        const recordCount = messages.length
        const { keys: recordDomains, urlCounts: recordUrlCounts, domainCount } = records
        const produce = outputs
            .queueMessages(ML_IMAGE_FETCH_OUTPUT, messages)
            .then(() => {
                // queueMessages resolves on the delivery acks, so `produced` counts what landed.
                MlMirrorMetrics.incrementMlUrlsCollected('produced', publishedCount)
                MlMirrorMetrics.incrementMlProducedVersion('url', mlWireVersion(key), recordCount)
                // A domain whose URLs fill several records reports once for each record. TopHog
                // sums the reports, so the total for the domain is its URL count.
                for (let index = 0; index < recordDomains.length; index++) {
                    producedUrlsByRegistrableDomain.record(
                        { registrable_domain: recordDomains[index] },
                        recordUrlCounts[index]
                    )
                }
                producedUrlsTotal.record({}, publishedCount)
            })
            .catch((error) => {
                // A dangling ref renders as a placeholder, so a failed produce is logged and never
                // thrown back into the pipeline. Un-mark the cache entries: the same image in a later
                // snapshot then produces again, one attempt for each recurrence and no retry loop.
                // A duplicate costs the fetcher one ledger read, because the ledger is keyed by ref.
                batch.release(producedUrls.cache)
                logger.warn('🌐', 'ml_image_fetch_produce_failed', {
                    count: publishedCount,
                    domains: domainCount,
                    error: String(error),
                })
                MlMirrorMetrics.incrementMlUrlsCollected('produce_failed', publishedCount)
                if (key) {
                    throw error
                }
            })
        return ok({ ...input, collectedUrls: undefined }, [produce])
    }
}

/** Outside the step's scope, so that the ack handlers share no closure context that holds the records. */
function fetchTopicMessages(records: UrlRecords, headers: Record<string, string>): IngestionOutputMessage[] {
    return records.keys.map((registrableDomain, index) => {
        const value = records.values[index]
        MlMirrorMetrics.observeMlUrlRecord(records.urlCounts[index], value.length)
        return { key: registrableDomain, value, headers }
    })
}
