import posthog from 'posthog-js'
import { PostHog } from 'posthog-js'

import {
    parseEncodedSnapshots as _parseEncodedSnapshots,
    ReplayTelemetry,
    SnappyDecompressor,
    RegisterWindowIdCallback,
} from '@posthog/replay-shared'

import { getDecompressionWorkerManager } from 'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager'

import { EncodedRecordingSnapshot, RecordingSnapshot } from '~/types'

export const posthogTelemetry: ReplayTelemetry = {
    capture: (event, properties) => posthog.capture(event, properties),
    captureException: (error, properties) => posthog.captureException(error, properties),
}

const createBrowserDecompressor = (posthogInstance?: PostHog): SnappyDecompressor => {
    return async (block: Uint8Array): Promise<Uint8Array> => {
        const workerManager = getDecompressionWorkerManager(posthogInstance)
        return workerManager.decompress(block)
    }
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
    sessionId: string,
    posthogInstance?: PostHog,
    registerWindowId?: RegisterWindowIdCallback
): Promise<RecordingSnapshot[]> => {
    return _parseEncodedSnapshots(
        items,
        sessionId,
        posthogTelemetry,
        registerWindowId,
        createBrowserDecompressor(posthogInstance)
    )
}
