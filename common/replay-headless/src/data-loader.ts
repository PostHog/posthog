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

import type { PlayerConfig, RecordingBlock } from './types'

async function fetchBlocks(config: PlayerConfig): Promise<RecordingBlock[]> {
    const url = `${config.recordingApiBaseUrl}/api/projects/${config.teamId}/recordings/${config.sessionId}/blocks`

    const response = await fetch(url, {
        headers: {
            'X-Internal-Api-Secret': config.recordingApiSecret,
        },
    })

    if (!response.ok) {
        const body = await response.text()
        throw new Error(`Failed to fetch block listing: ${response.status} ${response.statusText} - ${body}`)
    }

    const data: { blocks: RecordingBlock[] } = await response.json()
    return data.blocks
}

async function fetchBlock(config: PlayerConfig, block: RecordingBlock): Promise<string> {
    const url = `${config.recordingApiBaseUrl}/api/projects/${config.teamId}/recordings/${config.sessionId}/block`
    const params = new URLSearchParams({
        key: block.key,
        start: String(block.start),
        end: String(block.end),
        decompress: 'true',
    })

    const response = await fetch(`${url}?${params}`, {
        headers: {
            'X-Internal-Api-Secret': config.recordingApiSecret,
        },
    })

    if (!response.ok) {
        const body = await response.text()
        throw new Error(`Failed to fetch block: ${response.status} ${response.statusText} - ${body}`)
    }
    return response.text()
}

export interface LoadedSources {
    sources: SessionRecordingSnapshotSource[]
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse>
}

export async function loadAllSources(config: PlayerConfig): Promise<LoadedSources> {
    const blocks = await fetchBlocks(config)

    if (blocks.length === 0) {
        return { sources: [], snapshotsBySource: {} }
    }

    const registerWindowId = createWindowIdRegistry()
    const sources: SessionRecordingSnapshotSource[] = []
    const snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> = {}

    const results = await Promise.all(
        blocks.map(async (block, index) => {
            const text = await fetchBlock(config, block)
            const lines = text.split('\n').filter(Boolean)
            const snapshots: RecordingSnapshot[] = parseJsonSnapshots(
                lines,
                config.sessionId,
                noOpTelemetry,
                registerWindowId
            )
            return { index, snapshots }
        })
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
