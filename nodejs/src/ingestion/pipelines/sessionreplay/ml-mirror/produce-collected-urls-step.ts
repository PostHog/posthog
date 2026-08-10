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
 * sighting produces a second time, which costs topic volume and one more ledger read in the
 * fetcher, but never correctness. The fetcher dedupes on the same ref again.
 */
const PRODUCED_REF_CACHE_MAX = 500_000

/** One record on the fetch topic. The Kafka key is the host, so all URLs here have that one host. */
export interface CollectedUrlsMessage {
    /** The HMAC pseudonym of the team. The raw team id must not go onto this topic. */
    pseudoTeam: string
    /** When the mirror saw these URLs. The fetcher drops a message that is too old. */
    firstSeenMs: number
    urls: { ref: string; url: string }[]
}

/**
 * Produce the collected URLs of remote images to the fetch topic, keyed by host.
 *
 * The URLs of one replay message go into groups by host, and each group becomes one Kafka message.
 * A Kafka message has one key, and the key of this topic is the host, so a group can hold only one
 * host. A page usually loads its images from one or two hosts, so this makes tens of URLs into one
 * or two records.
 *
 * The step does not hold URLs across replay messages. The produce goes back as a pipeline side
 * effect, and the pipeline waits for the side effects of a batch before it commits the offsets of
 * that batch. A buffer that spans messages would break that guarantee, because the pipeline could
 * commit the offset of a message while the URLs of that message were still in the buffer. A crash
 * would then lose them. The group-by-host step already removes most of the record count, `linger.ms`
 * makes the batches on the wire, and the ref cache stops a repeated image before it produces at all.
 *
 * Delivery is not awaited and never fails the message. The mirrored lines already carry the refs,
 * and a ref with no image behind it renders as a placeholder.
 *
 * The `url` field is the original, unscrubbed URL. It is as sensitive as the raw replay payload, so
 * it goes only into the Kafka value. Log lines and metrics carry hosts and counts only.
 */
export function createProduceCollectedUrlsStep<T extends { collectedUrls?: CollectedUrl[] }>(
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

        // Every ref of one replay message belongs to one team, so one parse gives the pseudonym for
        // all of them. The pseudonym comes back out of the ref because the ref is the only place
        // the collector puts it. A ref that does not parse means the ref format drifted from the
        // one that `content-ref.ts` defines, and the fetcher would drop such a record anyway.
        const parsed = parseImageRef(fresh[0].ref)
        if (!parsed) {
            logger.error('🌐', 'ml_image_fetch_ref_unparseable', { count: fresh.length })
            return Promise.resolve(ok({ ...input, collectedUrls: undefined }))
        }

        const byHost = new Map<string, { ref: string; url: string }[]>()
        for (const entry of fresh) {
            producedRefs.add(entry.ref)
            const group = byHost.get(entry.host)
            if (group) {
                group.push({ ref: entry.ref, url: entry.url })
            } else {
                byHost.set(entry.host, [{ ref: entry.ref, url: entry.url }])
            }
        }
        SessionRecordingIngesterMetrics.incrementMlUrlsCollected('queued', fresh.length)

        const firstSeenMs = Date.now()
        const messages = [...byHost].map(([host, urls]) => ({
            key: host,
            value: Buffer.from(
                JSON.stringify({ pseudoTeam: parsed.pseudoTeam, firstSeenMs, urls } satisfies CollectedUrlsMessage)
            ),
        }))

        // The failure handler captures only the refs, so that a produce which is not yet delivered
        // does not hold the URL strings alive longer than the messages themselves.
        const refs = fresh.map((entry) => entry.ref)
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
                    hosts: byHost.size,
                    error: String(error),
                })
                SessionRecordingIngesterMetrics.incrementMlUrlsCollected('produce_failed', refs.length)
            })
        return Promise.resolve(ok({ ...input, collectedUrls: undefined }, [produce]))
    }
}
