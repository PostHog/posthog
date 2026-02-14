import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

export interface SourceEntry {
    source: SessionRecordingSnapshotSource
    index: number
    state: 'unloaded' | 'loaded'
    processedSnapshots: RecordingSnapshot[] | null
    fullSnapshotTimestamps: number[]
    metaTimestamps: number[]
    startMs: number
    endMs: number
}

export interface LoadBatch {
    sourceIndices: number[]
    reason: 'seek_target' | 'seek_backward' | 'seek_gap_fill' | 'buffer_ahead'
}

export interface SourceLoadingState {
    startMs: number
    endMs: number
    state: 'unloaded' | 'loaded'
}

export type Mode = { kind: 'buffer_ahead' } | { kind: 'seek'; targetTimestamp: number }
