import { LARGE_AI_PROPERTIES } from '~/ingestion/common/steps/event-processing/split-ai-events-step'
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
    aiBlobOffloadEventBytes,
    aiBlobOffloadEventsCounter,
    aiBlobOffloadTextBytes,
} from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

export interface OffloadAiBlobsStepConfig {
    enabledTeamIds: Set<number>
    minBase64Length: number
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

export function createOffloadAiBlobsStep<T extends OffloadAiBlobsInput>(
    store: BlobStore | null,
    config: OffloadAiBlobsStepConfig
): ProcessingStep<T, T> {
    return async function offloadAiBlobsStep(input) {
        if (!store || !config.enabledTeamIds.has(input.team.id)) {
            return ok(input)
        }

        const teamId = String(input.team.id)
        const properties = input.normalizedEvent.properties ?? {}
        const rewrittenProps: Record<string, unknown> = {}
        const blobsByHash = new Map<string, DetectedBlob>()
        let belowFloorCount = 0
        let belowFloorBytes = 0
        let bytesBefore = 0
        let bytesAfter = 0

        for (const key of LARGE_AI_PROPERTIES) {
            const value = properties[key]
            if (value === undefined || value === null) {
                continue
            }
            const extraction = extractBlobs(value, { minBase64Length: config.minBase64Length })
            belowFloorCount += extraction.belowFloorCount
            belowFloorBytes += extraction.belowFloorBytes
            const afterBytes = Buffer.byteLength(JSON.stringify(extraction.value))
            aiBlobOffloadTextBytes.observe(afterBytes)
            if (extraction.blobs.length === 0) {
                continue
            }
            for (const blob of extraction.blobs) {
                blobsByHash.set(blob.hash, blob)
            }
            rewrittenProps[key] = extraction.value
            bytesBefore += Buffer.byteLength(JSON.stringify(value))
            bytesAfter += afterBytes
        }

        if (belowFloorCount > 0) {
            aiBlobOffloadBelowFloorCounter.labels(teamId).inc(belowFloorCount)
            aiBlobOffloadBelowFloorBytes.labels(teamId).inc(belowFloorBytes)
        }

        if (blobsByHash.size === 0) {
            aiBlobOffloadEventsCounter.labels(teamId, 'no_blobs').inc()
            return ok(input)
        }

        const blobs = [...blobsByHash.values()]
        // Upload-before-emit: every blob must be confirmed durable before the
        // rewritten event exists anywhere. A failure rejects the step; the
        // pipeline's retry option owns transient failures.
        const outcomes = await Promise.all(blobs.map((blob) => store.ensureStored(input.team.id, blob)))

        blobs.forEach((blob, i) => {
            aiBlobOffloadBlobsCounter.labels(teamId, blob.detector, mimeFamily(blob.mime), outcomes[i]).inc()
            aiBlobOffloadBlobBytes.labels(mimeFamily(blob.mime)).observe(blob.bytes.length)
        })
        aiBlobOffloadBlobsPerEvent.observe(blobs.length)
        aiBlobOffloadEventBytes.labels('before').observe(bytesBefore)
        aiBlobOffloadEventBytes.labels('after').observe(bytesAfter)
        aiBlobOffloadEventsCounter.labels(teamId, 'offloaded').inc()

        return ok({
            ...input,
            normalizedEvent: {
                ...input.normalizedEvent,
                properties: { ...properties, ...rewrittenProps },
            },
        })
    }
}
