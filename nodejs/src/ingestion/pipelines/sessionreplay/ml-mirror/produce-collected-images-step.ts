import type { ClaimedImages, CollectedImageBatch } from '@posthog/replay-anonymizer'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { ML_IMAGE_SCRUB_OUTPUT, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlSessionKeys } from './keys/key-store'
import { mlKafkaHeaders, mlWireVersion, validateImageOwner } from './keys/transport'
import { MlMirrorMetrics } from './metrics'
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
        collectedImages?: CollectedImageBatch
        message: { timestamp?: number }
        mlKeys?: MlSessionKeys
    },
>(outputs: IngestionOutputs<MlImageScrubOutput>, producedRefs: ProducedImageRefs): ProcessingStep<T, T> {
    return function produceCollectedImagesStep(input) {
        const sessionId = input.headers?.session_id
        const key = sessionId && usesRawSessionIdentifiers(sessionId) ? input.mlKeys?.session : undefined
        const batch = input.collectedImages
        if (!batch) {
            return Promise.resolve(ok(input))
        }

        validateImageOwner(batch.firstRef, key)
        const claimed = batch.claim(producedRefs.cache)
        const count = claimed.refs.length
        MlMirrorMetrics.incrementMlImagesCollected('deduped', batch.count - count)
        if (count === 0) {
            return Promise.resolve(ok({ ...input, collectedImages: undefined }))
        }

        MlMirrorMetrics.incrementMlImagesCollected('queued', count)
        const captureTimestampMs = input.message.timestamp
        const headers = {
            ...(captureTimestampMs !== undefined && Number.isSafeInteger(captureTimestampMs) && captureTimestampMs > 0
                ? { [CAPTURE_TIMESTAMP_HEADER]: String(captureTimestampMs) }
                : {}),
            ...mlKafkaHeaders(mlWireVersion(key)),
        }
        const bytes = claimed.bytes
        const produce = outputs
            .queueMessages(ML_IMAGE_SCRUB_OUTPUT, scrubTopicMessages(claimed, headers))
            .then(() => {
                // queueMessages resolves on delivery acks, so `produced` counts what actually landed.
                MlMirrorMetrics.incrementMlImagesCollected('produced', count)
                MlMirrorMetrics.incrementMlProducedVersion('image', mlWireVersion(key), count)
                MlMirrorMetrics.incrementMlImageBytesProduced(bytes)
            })
            .catch((error) => {
                // A dangling ref reads as a placeholder downstream, so a failed produce is logged,
                // never re-thrown into the pipeline. Un-mark the refs: the same image recurring in
                // a later snapshot then re-produces naturally (one attempt per recurrence, no retry
                // loop), and duplicates are idempotent downstream (S3 keyed by hash).
                batch.release(producedRefs.cache)
                logger.warn('🖼️', 'ml_image_scrub_produce_failed', { count, error: String(error) })
                MlMirrorMetrics.incrementMlImagesCollected('produce_failed', count)
                if (key) {
                    throw error
                }
            })
        return Promise.resolve(ok({ ...input, collectedImages: undefined }, [produce]))
    }
}

/** Outside the step's scope, so that the ack handlers share no closure context that holds the images. */
function scrubTopicMessages(claimed: ClaimedImages, headers: Record<string, string>): IngestionOutputMessage[] {
    return claimed.refs.map((ref, index) => ({ key: ref, value: claimed.images[index], headers }))
}
