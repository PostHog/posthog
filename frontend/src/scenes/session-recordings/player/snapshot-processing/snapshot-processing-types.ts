import type { RecordingSnapshot } from '~/types'

export interface SnapshotProcessingRequest {
    id: number
    compressedData: Uint8Array
    sessionId: string
}

export interface WindowIdMapping {
    uuid: string
    index: number
}

export interface SnapshotProcessingResponse {
    id: number
    snapshots: RecordingSnapshot[] | null
    windowIdMappings: WindowIdMapping[]
    error?: string
    metrics?: {
        decompressDurationMs: number
        parseDurationMs: number
        snapshotCount: number
        lineCount: number
        compressionType: string
    }
}
