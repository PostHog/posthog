import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { ML_IMAGE_SCRUB_OUTPUT, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlSessionKeys } from './keys/key-store'
import { mlKafkaRecord, mlWireVersion, validateImageOwner } from './keys/transport'
import { MlMirrorMetrics } from './metrics'
import { CollectedImage } from './parse-and-anonymize-step'
import { ProducedImageRefs } from './produced-refs'
import { usesRawSessionIdentifiers } from './session-identifier-format'

/**
 * Produce collected original images to the scrub topic as a fire-and-forget side effect, keyed by
 * their `image:<teamId>:<hash>` ref. Delivery is deliberately not awaited and never blocks or
 * fails the message: the mirrored lines already carry the refs, and a ref whose image never lands
 * is defined as equivalent to a placeholder for training joins.
 *
 * The anonymize call already left out the refs an earlier batch produced. The claim here catches
 * the ones that two messages of one batch share.
 */
export function createProduceCollectedImagesStep<
    T extends {
        team?: { teamId: number }
        headers?: { session_id: string }
        collectedImages?: CollectedImage[]
        message: { timestamp?: number }
        mlKeys?: MlSessionKeys
    },
>(outputs: IngestionOutputs<MlImageScrubOutput>, producedRefs: ProducedImageRefs): ProcessingStep<T, T> {
    return function produceCollectedImagesStep(input) {
        const sessionId = input.headers?.session_id
        const key = sessionId && usesRawSessionIdentifiers(sessionId) ? input.mlKeys?.session : undefined
        const images = input.collectedImages
        if (!images?.length) {
            return Promise.resolve(ok(input))
        }

        const claimed = producedRefs.claim(images.map((image) => image.ref))
        const fresh = images.filter((_image, index) => claimed[index])
        MlMirrorMetrics.incrementMlImagesCollected('deduped', images.length - fresh.length)
        if (fresh.length === 0) {
            return Promise.resolve(ok({ ...input, collectedImages: undefined }))
        }

        let bytes = 0
        for (const image of fresh) {
            bytes += image.bytes.length
        }
        MlMirrorMetrics.incrementMlImagesCollected('queued', fresh.length)
        const captureTimestampMs = input.message.timestamp
        const headers =
            captureTimestampMs !== undefined && Number.isSafeInteger(captureTimestampMs) && captureTimestampMs > 0
                ? { [CAPTURE_TIMESTAMP_HEADER]: String(captureTimestampMs) }
                : undefined

        // The ack handlers must capture only the refs: `image.bytes` are subarray views into the
        // whole packed FFI buffer (up to 32 MB per source message), and queueMessages copies the
        // slices synchronously — a closure holding `fresh` would pin the full packed buffer per
        // in-flight produce, unbounded by the producer queue's byte accounting.
        const refs = fresh.map((image) => image.ref)
        const produce = outputs
            .queueMessages(
                ML_IMAGE_SCRUB_OUTPUT,
                fresh.map((image) => {
                    validateImageOwner(image.ref, key)
                    const record = mlKafkaRecord(mlWireVersion(key), image.bytes)
                    return { key: image.ref, value: record.value, headers: { ...headers, ...record.headers } }
                })
            )
            .then(() => {
                // queueMessages resolves on delivery acks, so `produced` counts what actually landed.
                MlMirrorMetrics.incrementMlImagesCollected('produced', refs.length)
                MlMirrorMetrics.incrementMlProducedVersion('image', mlWireVersion(key), refs.length)
                MlMirrorMetrics.incrementMlImageBytesProduced(bytes)
            })
            .catch((error) => {
                // A dangling ref reads as a placeholder downstream, so a failed produce is logged,
                // never re-thrown into the pipeline. Un-mark the refs: the same image recurring in
                // a later snapshot then re-produces naturally (one attempt per recurrence, no retry
                // loop), and duplicates are idempotent downstream (S3 keyed by hash).
                producedRefs.release(refs)
                logger.warn('🖼️', 'ml_image_scrub_produce_failed', { count: refs.length, error: String(error) })
                MlMirrorMetrics.incrementMlImagesCollected('produce_failed', refs.length)
                if (key) {
                    throw error
                }
            })
        return Promise.resolve(ok({ ...input, collectedImages: undefined }, [produce]))
    }
}
