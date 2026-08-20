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
 * ref of approximately 60 bytes and no image bytes. A ref that this cache drops before its next
 * arrival produces a second time, which costs topic volume and one more ledger read in the
 * fetcher, but never correctness. The fetcher dedupes on the same ref again.
 */
const PRODUCED_REF_CACHE_MAX = 500_000

/**
 * The URL payload one record may carry. The `message.max.bytes` default is 1,000,000 bytes and this
 * producer does not override it, so the remainder holds the envelope. The budget counts bytes
 * rather than URLs, because a URL can be as long as `MAX_URL_LEN`.
 */
const MAX_RECORD_URL_BYTES = 512 * 1024

/**
 * The URL count one record may carry. Without it the collector's cap in another crate decides the
 * count, and an increase there makes records the fetcher refuses whole. Keep it below
 * `MAX_URLS_PER_RECORD` in `ml-mirror-image-fetch/collected-urls-record.ts`.
 */
const MAX_RECORD_URLS = 512

export interface RecordUrl {
    ref: string
    url: string
    host: string
}

/** One record on the fetch topic. The Kafka key is the registrable domain, so every URL here
 *  belongs to one operator. Hosts can differ within it: a CDN sharding over img1..img8 keeps one
 *  budget but still needs its own robots.txt and connection limit per host. */
export interface CollectedUrlsMessage {
    /**
     * The wire format version. The fetcher reads this topic from another deployment, so the two
     * sides roll separately and a reader needs to know what it is holding.
     */
    v: 1
    /** The HMAC pseudonym of the team. The raw team id must not go onto this topic. */
    pseudoTeam: string
    /**
     * When capture recorded the replay message these URLs came from, not when the mirror produced
     * them. The fetcher drops a record that is too old, and produce time cannot answer that: a
     * mirror replaying a backlog would stamp hours-old URLs as fresh, which is the one case the
     * age check exists for.
     */
    capturedAtMs: number
    urls: RecordUrl[]
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
 * makes the batches on the wire, and the ref cache stops a repeated image before it produces at all.
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
    producedRefCacheMax: number = PRODUCED_REF_CACHE_MAX
): ProcessingStep<T, T> {
    const producedRefs = new RefDedupCache('image_fetch_producer', producedRefCacheMax)

    return function produceCollectedUrlsStep(input) {
        const collected = input.collectedUrls
        if (!collected?.length) {
            return Promise.resolve(ok(input))
        }

        const fresh = collected.filter((entry) => !producedRefs.has(entry.ref))
        SessionRecordingIngesterMetrics.incrementMlUrlsCollected('deduped', collected.length - fresh.length)
        if (fresh.length === 0) {
            return Promise.resolve(ok({ ...input, collectedUrls: undefined }))
        }

        // Each entry is checked, not just the first. A `bytes` ref names an image the page
        // inlined, and its hash can never be reproduced from a URL, so a record carrying one
        // reaches the fetcher under a hash nothing will ever match. Both kinds parse, so only
        // `source` separates them, and checking one entry would let every later one through.
        //
        // The pseudonym comes back out of the ref, because the ref is the only place the collector
        // puts it. Every entry must agree on it: one replay message belongs to one team, and a
        // record stamped with another team's pseudonym is a tenant-attribution error that nothing
        // downstream can detect.
        const usable: CollectedUrl[] = []
        let pseudoTeam: string | undefined
        for (const entry of fresh) {
            const parsed = parseImageRef(entry.ref)
            if (!parsed || parsed.source !== 'url' || (pseudoTeam && parsed.pseudoTeam !== pseudoTeam)) {
                continue
            }
            pseudoTeam ??= parsed.pseudoTeam
            usable.push(entry)
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

        const byDomain = new Map<string, RecordUrl[]>()
        for (const entry of usable) {
            producedRefs.add(entry.ref)
            const group = byDomain.get(entry.domain)
            const record: RecordUrl = { ref: entry.ref, url: entry.url, host: entry.host }
            SessionRecordingIngesterMetrics.observeMlUrlBytes(Buffer.byteLength(entry.url))
            if (group) {
                group.push(record)
            } else {
                byDomain.set(entry.domain, [record])
            }
        }
        SessionRecordingIngesterMetrics.incrementMlUrlsCollected('queued', usable.length)

        // The capture timestamp of the source Kafka record, so the fetcher's age check measures the
        // age of the replay data rather than the age of this produce. librdkafka reports an absent
        // timestamp as -1, which is not nullish, so a plain ?? would ship a negative age.
        const messageTimestamp = input.message.timestamp
        const capturedAtMs = messageTimestamp !== undefined && messageTimestamp > 0 ? messageTimestamp : Date.now()
        const messages = [...byDomain].flatMap(([domain, urls]) =>
            packByBytes(urls, MAX_RECORD_URL_BYTES).map((slice) => {
                const value = Buffer.from(
                    JSON.stringify({
                        v: 1,
                        pseudoTeam,
                        capturedAtMs,
                        urls: slice,
                    } satisfies CollectedUrlsMessage)
                )
                SessionRecordingIngesterMetrics.observeMlUrlRecord(slice.length, value.length)
                return { key: domain, value }
            })
        )

        // The failure handler captures only the refs, so that a produce which is not yet delivered
        // does not hold the URL strings alive longer than the messages themselves.
        const refs = usable.map((entry) => entry.ref)
        const produce = outputs
            .queueMessages(ML_IMAGE_FETCH_OUTPUT, messages)
            .then(() => {
                // queueMessages resolves on the delivery acks, so `produced` counts what landed.
                SessionRecordingIngesterMetrics.incrementMlUrlsCollected('produced', refs.length)
            })
            .catch((error) => {
                // A dangling ref renders as a placeholder, so a failed produce is logged and never
                // thrown back into the pipeline. Un-mark the refs: the same image in a later
                // snapshot then produces again, one attempt for each recurrence and no retry loop.
                // A duplicate costs the fetcher one ledger read, because the ledger is keyed by ref.
                for (const ref of refs) {
                    producedRefs.delete(ref)
                }
                logger.warn('🌐', 'ml_image_fetch_produce_failed', {
                    count: refs.length,
                    domains: byDomain.size,
                    error: String(error),
                })
                SessionRecordingIngesterMetrics.incrementMlUrlsCollected('produce_failed', refs.length)
            })
        return Promise.resolve(ok({ ...input, collectedUrls: undefined }, [produce]))
    }
}

/**
 * An entry always goes into a record, even alone in one above the budget, because a drop here loses
 * an image that every earlier check accepted. `MAX_URL_LEN` keeps that record under the broker
 * limit.
 */
function packByBytes(entries: RecordUrl[], maxBytes: number): RecordUrl[][] {
    const out: RecordUrl[][] = []
    let current: RecordUrl[] = []
    let bytes = 0
    for (const entry of entries) {
        const size = entryBytes(entry)
        if (current.length > 0 && (bytes + size > maxBytes || current.length >= MAX_RECORD_URLS)) {
            out.push(current)
            current = []
            bytes = 0
        }
        current.push(entry)
        bytes += size
    }
    if (current.length > 0) {
        out.push(current)
    }
    return out
}

/**
 * `JSON.stringify` widens a quote or a backslash, so this count is a lower bound. Canonicalization
 * percent-encodes both upstream, and the budget is half the broker limit, so the estimate has room.
 * The `ml_url_record_bytes` metric shows that margin if it shrinks.
 */
const ENTRY_OVERHEAD_BYTES = '{"ref":"","url":"","host":""},'.length

function entryBytes(entry: RecordUrl): number {
    return (
        Buffer.byteLength(entry.ref) +
        Buffer.byteLength(entry.url) +
        Buffer.byteLength(entry.host) +
        ENTRY_OVERHEAD_BYTES
    )
}
