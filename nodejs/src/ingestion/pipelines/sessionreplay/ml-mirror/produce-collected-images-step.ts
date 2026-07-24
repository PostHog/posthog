import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { CollectedImage } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { ML_IMAGE_SCRUB_OUTPUT, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

/**
 * The Rust collector only dedupes within one message, leaving this as the sole thing between a hot
 * sprite and one produce per recurrence, so capacity translates directly into scrub-topic volume: a
 * ref evicted before its next sighting is re-produced and re-scrubbed. Budget ~200 B per entry (the
 * LRU's bookkeeping dominates the ~60 B ref), so this is ~100 MB against the 8000M mirror container
 * in https://github.com/PostHog/charts/blob/main/apps/ingestion-sessionreplay-ml-mirror/values.yaml,
 * which also holds the anonymizer's packed image buffers. Overflowing it costs topic bytes rather
 * than correctness, since the consumer dedupes by ref too.
 */
const PRODUCED_REF_CACHE_MAX = 500_000

/**
 * Produce collected original images to the scrub topic as a fire-and-forget side effect, keyed by
 * their `image:<pseudoTeam>:<hash>` ref. Delivery is deliberately not awaited and never blocks or
 * fails the message: the mirrored lines already carry the refs, and a ref whose image never lands
 * is defined as equivalent to a placeholder for training joins.
 */
export function createProduceCollectedImagesStep<T extends { collectedImages?: CollectedImage[] }>(
    outputs: IngestionOutputs<MlImageScrubOutput>,
    producedRefCacheMax: number = PRODUCED_REF_CACHE_MAX
): ProcessingStep<T, T> {
    const producedRefs = new RefDedupCache('image_scrub_producer', producedRefCacheMax)

    return function produceCollectedImagesStep(input) {
        const images = input.collectedImages
        if (!images?.length) {
            return Promise.resolve(ok(input))
        }

        const fresh = images.filter((image) => !producedRefs.has(image.ref))
        SessionRecordingIngesterMetrics.incrementMlImagesCollected('deduped', images.length - fresh.length)
        if (fresh.length === 0) {
            return Promise.resolve(ok({ ...input, collectedImages: undefined }))
        }

        let bytes = 0
        for (const image of fresh) {
            producedRefs.add(image.ref)
            bytes += image.bytes.length
        }
        SessionRecordingIngesterMetrics.incrementMlImagesCollected('queued', fresh.length)

        // The ack handlers must capture only the refs: `image.bytes` are subarray views into the
        // whole packed FFI buffer (up to 32 MB per source message), and queueMessages copies the
        // slices synchronously — a closure holding `fresh` would pin the full packed buffer per
        // in-flight produce, unbounded by the producer queue's byte accounting.
        const refs = fresh.map((image) => image.ref)
        const produce = outputs
            .queueMessages(
                ML_IMAGE_SCRUB_OUTPUT,
                fresh.map((image) => ({ key: image.ref, value: image.bytes }))
            )
            .then(() => {
                // queueMessages resolves on delivery acks, so `produced` counts what actually landed.
                SessionRecordingIngesterMetrics.incrementMlImagesCollected('produced', refs.length)
                SessionRecordingIngesterMetrics.incrementMlImageBytesProduced(bytes)
            })
            .catch((error) => {
                // A dangling ref reads as a placeholder downstream, so a failed produce is logged,
                // never re-thrown into the pipeline. Un-mark the refs: the same image recurring in
                // a later snapshot then re-produces naturally (one attempt per recurrence, no retry
                // loop), and duplicates are idempotent downstream (S3 keyed by hash).
                for (const ref of refs) {
                    producedRefs.delete(ref)
                }
                logger.warn('🖼️', 'ml_image_scrub_produce_failed', { count: refs.length, error: String(error) })
                SessionRecordingIngesterMetrics.incrementMlImagesCollected('produce_failed', refs.length)
            })
        return Promise.resolve(ok({ ...input, collectedImages: undefined }, [produce]))
    }
}
