import { ImageScrubEmitDeps } from '~/ingestion/pipelines/sessionreplay/ml-mirror/image-scrub/producer'

import { AllowLists } from './allow-lists'

/** Replacement char for redacted (non-allow-listed) word characters. */
export const REDACT_CHAR = '*'
/** Replacement char for numeric tokens. */
export const NUMBER_CHAR = '#'

/** A deferred image-blur job: an async closure that blurs its image and writes the result back in place. */
export type BlurJob = () => Promise<void>

/** In-batch blur memo (input → settled blur): one per Kafka message, so an image recurring across its rrweb events blurs once. */
export type BlurCache = Map<string, Promise<string | null>>

/** Diagnostic accumulator (ms) for the cv gzip de/recompression sub-steps. */
export interface ScrubTiming {
    decompressMs: number
    recompressMs: number
}

/** An advanced-route image to hand off to the scrub topic: raw bytes to emit, plus a callback that
 *  writes the resolved `image:{team}:{hash}` reference back over the inline image. */
export interface ImageScrubJob {
    bytes: Buffer
    apply: (ref: string) => void
}

/** Per-scrub context: the active allow lists plus tunables read by the scrubbers. */
export interface ScrubContext {
    allow: AllowLists
    /** Optional collector for deferred image-blur jobs (see {@link BlurJob}). */
    blurJobs?: BlurJob[]
    /** Optional per-Kafka-message memo shared across those jobs so identical images blur once (see {@link BlurCache}). */
    blurCache?: BlurCache
    /** Optional diagnostic timing accumulator (see {@link ScrubTiming}). */
    timing?: ScrubTiming
    /** Team id of the message being scrubbed — needed to build team-scoped image references. */
    teamId?: number
    /** Image-scrub emit dependencies (Redis dedup + Kafka produce); present only in the ml-mirror
     *  pipeline. When set, advanced-route images are hashed, referenced, and emitted to the scrub
     *  topic; when absent, they fall back to the in-process blur so other pipelines are unaffected. */
    imageScrub?: ImageScrubEmitDeps
    /** Collector for advanced-route images awaiting a batched emit (see {@link ImageScrubJob}). */
    imageScrubJobs?: ImageScrubJob[]
}

/** Shared non-null-object type guard used across the scrubbers. */
export function isObject(v: unknown): v is Record<string, any> {
    return typeof v === 'object' && v !== null
}
