import { LARGE_AI_PROPERTIES } from '~/ingestion/common/subpipelines/large-ai-properties'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { BlobStore, EnsureStoredOutcome } from '~/ingestion/pipelines/ai/blob-offload/blob-store'
import { DetectedBlob, extractBlobs } from '~/ingestion/pipelines/ai/blob-offload/detect'
import {
    aiBlobOffloadBelowFloorBytes,
    aiBlobOffloadBelowFloorCounter,
    aiBlobOffloadBlobBytes,
    aiBlobOffloadBlobsCounter,
    aiBlobOffloadBlobsPerEvent,
    aiBlobOffloadEventBytesSaved,
    aiBlobOffloadEventsCounter,
} from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'
import { Team, ValueMatcher } from '~/types'

export interface OffloadAiBlobsConfig {
    /** Gates offload per team; events from non-matching teams pass through with a null plan. */
    isTeamEnabled: ValueMatcher<number>
    /**
     * Minimum base64 payload length for a data URI to count as an offloadable
     * blob. Shorter payloads stay inline and are only counted as below-floor
     * in metrics.
     */
    minBase64Length: number
    /**
     * Cap on distinct (hash-deduplicated) blobs per event. Exceeding it skips
     * offload for the whole event rather than offloading a subset, so the
     * event passes through as if detection had missed.
     */
    maxBlobsPerEvent: number
    /**
     * Chunk-wide cap on concurrent blob uploads (applied via the fan-out
     * stage's `concurrently` block), so a many-blob chunk can't monopolize the
     * S3 socket pool and per-request timeouts start when a request runs, not
     * when it's queued.
     */
    uploadMaxConcurrency: number
}

type OffloadAiBlobsInput = {
    normalizedEvent: PluginEvent
    team: Team
}

const MIME_FAMILIES = new Set(['image', 'audio', 'video', 'text', 'application'])

function mimeFamily(mime: string): string {
    const family = mime.split('/')[0]
    return MIME_FAMILIES.has(family) ? family : 'other'
}

/**
 * Everything the extraction step computed that the fan-in needs to finish the
 * offload once the blobs are durable. Metrics recording is deferred to the
 * fan-in so nothing is counted for an event whose uploads ultimately fail.
 */
interface AiBlobOffloadPlan {
    /** Deduplicated blobs to upload; empty when skipReason is set. */
    blobs: DetectedBlob[]
    /** Heavy properties rewritten with blob pointers, applied on fan-in. */
    rewrittenProps: Record<string, unknown>
    savedChars: number
    belowFloorCount: number
    belowFloorBytes: number
    skipReason: 'no_blobs' | 'blob_limit_exceeded' | null
}

export type WithAiBlobOffloadPlan<T> = T & { aiBlobOffloadPlan: AiBlobOffloadPlan | null }

export interface PendingAiBlobUpload {
    teamId: number
    blob: DetectedBlob
}

export interface UploadedAiBlob {
    blob: DetectedBlob
    outcome: EnsureStoredOutcome
}

/**
 * Cheap sequential step: detect blobs in the heavy AI properties and attach an
 * offload plan to the event. No I/O and no metrics — uploads happen in the
 * fan-out/fan-in stage's subpipeline, and metrics are recorded on fan-in.
 * A null plan means offload is disabled for this event (no store, or team not
 * enrolled) and the event passes through the stage untouched.
 */
export function createExtractAiBlobsStep<T extends OffloadAiBlobsInput>(
    store: BlobStore | null,
    config: OffloadAiBlobsConfig
): ProcessingStep<T, WithAiBlobOffloadPlan<T>> {
    const extractionOpts = { minBase64Length: config.minBase64Length }
    return function extractAiBlobsStep(input) {
        if (!store || !config.isTeamEnabled(input.team.id)) {
            return Promise.resolve(ok({ ...input, aiBlobOffloadPlan: null }))
        }

        const properties = input.normalizedEvent.properties ?? {}
        const rewrittenProps: Record<string, unknown> = {}
        const blobsByHash = new Map<string, DetectedBlob>()
        let savedChars = 0
        let belowFloorCount = 0
        let belowFloorBytes = 0

        for (const key of LARGE_AI_PROPERTIES) {
            const value = properties[key]
            if (value === undefined || value === null) {
                continue
            }
            const extraction = extractBlobs(value, extractionOpts)
            belowFloorCount += extraction.belowFloorCount
            belowFloorBytes += extraction.belowFloorBytes
            if (extraction.blobs.length === 0) {
                continue
            }
            for (const blob of extraction.blobs) {
                blobsByHash.set(blob.hash, blob)
            }
            rewrittenProps[key] = extraction.value
            savedChars += extraction.savedChars
        }

        const plan: AiBlobOffloadPlan = {
            blobs: [],
            rewrittenProps,
            savedChars,
            belowFloorCount,
            belowFloorBytes,
            skipReason: null,
        }
        if (blobsByHash.size === 0) {
            plan.skipReason = 'no_blobs'
        } else if (blobsByHash.size > config.maxBlobsPerEvent) {
            // Skipping entirely (rather than offloading a subset) keeps the conservative
            // posture: the event passes through exactly as if detection had missed.
            plan.skipReason = 'blob_limit_exceeded'
        } else {
            plan.blobs = [...blobsByHash.values()]
        }
        return Promise.resolve(ok({ ...input, aiBlobOffloadPlan: plan }))
    }
}

/** Fan-out: one sub-element per blob to upload; disabled/skipped events fan out to nothing. */
export function extractAiBlobsFanOut<T extends OffloadAiBlobsInput>(
    input: WithAiBlobOffloadPlan<T>
): PendingAiBlobUpload[] {
    const plan = input.aiBlobOffloadPlan
    if (!plan || plan.skipReason) {
        return []
    }
    return plan.blobs.map((blob) => ({ teamId: input.team.id, blob }))
}

/**
 * Per-blob upload step. Upload-before-emit: every blob must be confirmed
 * durable before the rewritten event exists anywhere. Failure contract, in
 * concert with the step's retry options and the store's error contract
 * (BlobStoreError): a non-retriable store failure means this blob can never
 * be stored — determined by the event's own content — and becomes a DLQ
 * sub-result, which the fan-out stage aggregates into a parent-level DLQ;
 * the event dead-letters instead of being emitted with pointers to blobs
 * that were never stored. Retriable store failures (transient or
 * environment-wide) retry and, on exhaustion, crash the consumer;
 * environment-wide problems are also caught before traffic by the store's
 * startup healthcheck.
 */
export function createUploadAiBlobStep(store: BlobStore | null): ProcessingStep<PendingAiBlobUpload, UploadedAiBlob> {
    return async function uploadAiBlobStep(upload) {
        if (!store) {
            // Extraction never fans out without a store, so this is a wiring bug.
            throw new Error('AI blob upload step invoked without a configured blob store')
        }
        const outcome = await store.ensureStored(upload.teamId, upload.blob)
        return ok({ blob: upload.blob, outcome })
    }
}

/**
 * Fan-in: only reached when every upload succeeded (or nothing fanned out).
 * Records the offload metrics and applies the rewritten properties, dropping
 * the plan (and the blob buffers it holds) from the value.
 */
export function mergeAiBlobPointersFanIn<T extends WithAiBlobOffloadPlan<OffloadAiBlobsInput>>(
    original: T,
    uploads: UploadedAiBlob[]
): Omit<T, 'aiBlobOffloadPlan' | 'normalizedEvent'> & { normalizedEvent: PluginEvent } {
    const { aiBlobOffloadPlan: plan, normalizedEvent, ...rest } = original
    if (!plan) {
        return { ...rest, normalizedEvent }
    }

    if (plan.belowFloorCount > 0) {
        aiBlobOffloadBelowFloorCounter.inc(plan.belowFloorCount)
        aiBlobOffloadBelowFloorBytes.inc(plan.belowFloorBytes)
    }

    if (plan.skipReason) {
        aiBlobOffloadEventsCounter.labels(plan.skipReason).inc()
        return { ...rest, normalizedEvent }
    }

    for (const { blob, outcome } of uploads) {
        aiBlobOffloadBlobsCounter.labels(blob.detector, mimeFamily(blob.mime), outcome).inc()
        aiBlobOffloadBlobBytes.labels(mimeFamily(blob.mime)).observe(blob.bytes.length)
    }
    aiBlobOffloadBlobsPerEvent.observe(uploads.length)
    aiBlobOffloadEventBytesSaved.observe(plan.savedChars)
    aiBlobOffloadEventsCounter.labels('offloaded').inc()

    const properties = normalizedEvent.properties ?? {}
    return {
        ...rest,
        normalizedEvent: {
            ...normalizedEvent,
            properties: { ...properties, ...plan.rewrittenProps },
        },
    }
}
