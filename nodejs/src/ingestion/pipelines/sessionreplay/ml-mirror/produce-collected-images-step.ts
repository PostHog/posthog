import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { CollectedImage } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { ML_IMAGE_SCRUB_OUTPUT, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

/**
 * The Rust collector dedupes within one message; this bounds cross-message re-produces (the same
 * sprite recurring in every snapshot of a session). Refs are ~60 bytes, so the ceiling is ~6 MB.
 * Duplicates that slip past it are only wasted topic bytes — the consumer's S3 layout is keyed by
 * hash, so re-produces are idempotent.
 */
const PRODUCED_REF_CACHE_MAX = 100_000

/**
 * Produce collected original images to the scrub topic as a fire-and-forget side effect, keyed by
 * their `image:<pseudoTeam>:<hash>` ref. Delivery is deliberately not awaited and never blocks or
 * fails the message: the mirrored lines already carry the refs, and a ref whose image never lands
 * is defined as equivalent to a placeholder for training joins.
 */
export function createProduceCollectedImagesStep<T extends { collectedImages?: CollectedImage[] }>(
    outputs: IngestionOutputs<MlImageScrubOutput>
): ProcessingStep<T, T> {
    const producedRefs = new Set<string>()

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

        if (producedRefs.size + fresh.length > PRODUCED_REF_CACHE_MAX) {
            producedRefs.clear()
        }
        let bytes = 0
        for (const image of fresh) {
            producedRefs.add(image.ref)
            bytes += image.bytes.length
        }
        SessionRecordingIngesterMetrics.incrementMlImagesCollected('queued', fresh.length)

        const produce = outputs
            .queueMessages(
                ML_IMAGE_SCRUB_OUTPUT,
                fresh.map((image) => ({ key: image.ref, value: image.bytes }))
            )
            .then(() => {
                // queueMessages resolves on delivery acks, so `produced` counts what actually landed.
                SessionRecordingIngesterMetrics.incrementMlImagesCollected('produced', fresh.length)
                SessionRecordingIngesterMetrics.incrementMlImageBytesProduced(bytes)
            })
            .catch((error) => {
                // A dangling ref reads as a placeholder downstream, so a failed produce is logged,
                // never re-thrown into the pipeline. Un-mark the refs: the same image recurring in
                // a later snapshot then re-produces naturally (one attempt per recurrence, no retry
                // loop), and duplicates are idempotent downstream (S3 keyed by hash).
                for (const image of fresh) {
                    producedRefs.delete(image.ref)
                }
                logger.warn('🖼️', 'ml_image_scrub_produce_failed', { count: fresh.length, error: String(error) })
                SessionRecordingIngesterMetrics.incrementMlImagesCollected('produce_failed', fresh.length)
            })
        return Promise.resolve(ok({ ...input, collectedImages: undefined }, [produce]))
    }
}
