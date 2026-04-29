import pLimit from 'p-limit'

import {
    parseJsonSnapshots,
    noOpTelemetry,
    createWindowIdRegistry,
    keyForSource,
    SnapshotSourceType,
    type RecordingSnapshot,
    type SessionRecordingSnapshotSource,
    type SessionRecordingSnapshotSourceResponse,
    type SourceKey,
} from '@posthog/replay-shared'

import { BLOCK_REQUEST_PREFIX } from './protocol'
import type { PlayerConfig } from './types'

export class DataLoadError extends Error {
    readonly statusCode: number
    readonly retryable: boolean

    constructor(message: string, statusCode: number) {
        super(message)
        this.name = 'DataLoadError'
        this.statusCode = statusCode
        this.retryable = statusCode >= 500 || statusCode === 429
    }
}

const MAX_CONCURRENT_FETCHES = 6
const MAX_BLOCK_RETRIES = 3
const INITIAL_RETRY_DELAY_MS = 500

async function withRetry<T>(fn: () => Promise<T>, retries = MAX_BLOCK_RETRIES): Promise<T> {
    let lastError: unknown
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            return await fn()
        } catch (err) {
            lastError = err
            const isRetryable = err instanceof DataLoadError && err.retryable
            if (!isRetryable || attempt === retries) {
                throw err
            }
            await new Promise((resolve) => setTimeout(resolve, INITIAL_RETRY_DELAY_MS * 2 ** attempt))
        }
    }
    throw lastError
}

async function fetchBlock(index: number): Promise<string> {
    const response = await fetch(`${BLOCK_REQUEST_PREFIX}${index}`)

    if (!response.ok) {
        const body = await response.text()
        throw new DataLoadError(
            `Failed to fetch block: ${response.status} ${response.statusText} - ${body}`,
            response.status
        )
    }
    return response.text()
}

export interface LoadedSources {
    sources: SessionRecordingSnapshotSource[]
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse>
}

export async function loadAllSources(
    config: PlayerConfig,
    onProgress?: (loaded: number, total: number) => void
): Promise<LoadedSources> {
    const { blockCount } = config

    if (blockCount === 0) {
        return { sources: [], snapshotsBySource: {} }
    }

    const registerWindowId = createWindowIdRegistry()
    const sources: SessionRecordingSnapshotSource[] = []
    const snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> = {}

    let blocksLoaded = 0
    onProgress?.(0, blockCount)

    const limit = pLimit(MAX_CONCURRENT_FETCHES)
    const results = await Promise.all(
        Array.from({ length: blockCount }, (_, index) =>
            limit(async () => {
                const text = await withRetry(() => fetchBlock(index))
                const lines = text.split('\n').filter(Boolean)
                const snapshots: RecordingSnapshot[] = parseJsonSnapshots(
                    lines,
                    config.sessionId,
                    noOpTelemetry,
                    registerWindowId
                )
                onProgress?.(++blocksLoaded, blockCount)
                return { index, snapshots }
            })
        )
    )

    for (const { index, snapshots } of results) {
        const source: SessionRecordingSnapshotSource = {
            source: SnapshotSourceType.blob_v2,
            blob_key: String(index),
        }
        sources.push(source)
        const key = keyForSource(source)
        snapshotsBySource[key] = { snapshots, sourceLoaded: true }
    }

    return { sources, snapshotsBySource }
}
