import { LARGE_AI_PROPERTIES } from '~/ingestion/common/subpipelines/large-ai-properties'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { BlobStore } from '~/ingestion/pipelines/ai/blob-offload/blob-store'
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
    isTeamEnabled: ValueMatcher<number>
    minBase64Length: number
    maxBlobsPerEvent: number
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

const MAX_CONCURRENT_UPLOADS = 8

async function mapWithConcurrency<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
    const results = new Array<R>(items.length)
    let next = 0
    const worker = async (): Promise<void> => {
        while (next < items.length) {
            const i = next++
            results[i] = await fn(items[i])
        }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
    return results
}

export function createOffloadAiBlobsStep<T extends OffloadAiBlobsInput>(
    store: BlobStore | null,
    config: OffloadAiBlobsConfig
): ProcessingStep<T, T> {
    return async function offloadAiBlobsStep(input) {
        if (!store || !config.isTeamEnabled(input.team.id)) {
            return ok(input)
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
            const extraction = extractBlobs(value, { minBase64Length: config.minBase64Length })
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

        // Deferred until the step can no longer reject, so retried attempts don't re-count.
        const recordBelowFloor = (): void => {
            if (belowFloorCount > 0) {
                aiBlobOffloadBelowFloorCounter.inc(belowFloorCount)
                aiBlobOffloadBelowFloorBytes.inc(belowFloorBytes)
            }
        }

        if (blobsByHash.size === 0) {
            recordBelowFloor()
            aiBlobOffloadEventsCounter.labels('no_blobs').inc()
            return ok(input)
        }

        // Skipping entirely (rather than offloading a subset) keeps the conservative
        // posture: the event passes through exactly as if detection had missed.
        if (blobsByHash.size > config.maxBlobsPerEvent) {
            recordBelowFloor()
            aiBlobOffloadEventsCounter.labels('blob_limit_exceeded').inc()
            return ok(input)
        }

        const blobs = [...blobsByHash.values()]
        // Upload-before-emit: every blob must be confirmed durable before the
        // rewritten event exists anywhere. A failure rejects the step; the
        // pipeline's retry option owns transient failures. Concurrency is bounded
        // so a many-blob event can't monopolize the S3 socket pool, and the
        // per-request timeout starts when a request runs, not when it's queued.
        const outcomes = await mapWithConcurrency(blobs, MAX_CONCURRENT_UPLOADS, (blob) =>
            store.ensureStored(input.team.id, blob)
        )

        recordBelowFloor()
        blobs.forEach((blob, i) => {
            aiBlobOffloadBlobsCounter.labels(blob.detector, mimeFamily(blob.mime), outcomes[i]).inc()
            aiBlobOffloadBlobBytes.labels(mimeFamily(blob.mime)).observe(blob.bytes.length)
        })
        aiBlobOffloadBlobsPerEvent.observe(blobs.length)
        aiBlobOffloadEventBytesSaved.observe(savedChars)
        aiBlobOffloadEventsCounter.labels('offloaded').inc()

        return ok({
            ...input,
            normalizedEvent: {
                ...input.normalizedEvent,
                properties: { ...properties, ...rewrittenProps },
            },
        })
    }
}
