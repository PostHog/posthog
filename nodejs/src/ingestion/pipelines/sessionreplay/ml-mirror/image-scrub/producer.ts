// Producer-side logic for the image-scrub topic, run inline by the ml-mirror anonymize pipeline. A block
// can carry many inlined images and a Redis RTT per image dominates, so the API is batched: one Redis
// round-trip dedups all advanced-route images in the message, one Kafka send posts the fresh ones. Each
// image's team-scoped reference replaces its inline `rr_dataURL` (caller does the swap); the raw image is
// posted only on its first sighting within the TTL, and the consumer later writes the scrubbed result to
// S3. Redis presence means "posted recently" (dedup), not "scrubbed image exists in S3". Reserve/release/
// produce are injected so this stays pure and unit-testable. Kept in sync with content-ref.ts CONTRACT.
import { hashImageBytes, imageRef } from './content-ref'
import { ImageScrubMetrics } from './metrics'

export const DEDUP_TTL_SECONDS = 24 * 60 * 60 // 24h window; ~2.6GB raw keys at 20M/day, fits a 10GB Redis

export interface TopicMessage {
    key: string
    value: Buffer
}

export interface ImageInput {
    teamId: number
    bytes: Buffer
}

/** Injected side-effects: batched Redis reserve/release + a batched topic produce. */
export interface ImageScrubEmitDeps {
    /** SET NX EX a batch of content-hash keys in Redis, in one round-trip. Returns, per key in order,
     *  whether it was newly set (true = first sighting within the TTL, so post it; false = a recent or
     *  in-batch duplicate). */
    setBatchContentKeysRedis: (keys: string[], ttlSeconds: number) => Promise<boolean[]>
    /** DEL a batch of content-hash keys in Redis; rolls the reservations back after a failed produce. */
    deleteBatchContentKeysRedis: (keys: string[]) => Promise<void>
    /** Produce a batch of raw-image messages to the scrub topic; resolves once the broker acks them. */
    produceBatchImagesKafka: (messages: TopicMessage[]) => Promise<void>
    ttlSeconds?: number
}

export interface EmitResult {
    /** Reference to substitute for the inline image, e.g. `image:42:a1B2...`. */
    ref: string
    /** True if this call posted the image; false if a recent (or in-batch) duplicate suppressed it. */
    posted: boolean
}

/**
 * Dedup a message's images in one Redis round-trip, post the fresh ones in one Kafka send. Rolls the
 * reservations back on produce failure so a stuck reservation can't dedup every later sighting until the
 * TTL expires. Returns one result per input image, in order. Throws if the produce fails after rollback,
 * so fail-closed ml-mirror drops the message rather than record references whose images never got posted.
 */
export async function emitImagesForScrub(images: ImageInput[], deps: ImageScrubEmitDeps): Promise<EmitResult[]> {
    if (images.length === 0) {
        return []
    }
    const refs = images.map((img) => imageRef(img.teamId, hashImageBytes(img.bytes)))
    const ttl = deps.ttlSeconds ?? DEDUP_TTL_SECONDS

    const fresh = await deps.setBatchContentKeysRedis(refs, ttl)

    const toPost: TopicMessage[] = []
    for (let i = 0; i < images.length; i++) {
        if (fresh[i]) {
            toPost.push({ key: refs[i], value: images[i].bytes })
        }
    }
    if (toPost.length > 0) {
        try {
            await deps.produceBatchImagesKafka(toPost)
        } catch (err) {
            // Roll back reservations so later sightings retry; if rollback itself fails (Redis down) the
            // keys sit until the TTL and dedup those images away, so meter it to stay visible.
            await deps
                .deleteBatchContentKeysRedis(toPost.map((m) => m.key))
                .catch(() => ImageScrubMetrics.incrementReservationRollbackFailure())
            throw err
        }
    }
    return refs.map((ref, i) => ({ ref, posted: fresh[i] }))
}
