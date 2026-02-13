import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

export interface SourceEntry {
    source: SessionRecordingSnapshotSource
    index: number
    state: 'unloaded' | 'loaded' | 'evicted'
    processedSnapshots: RecordingSnapshot[] | null
    fullSnapshotTimestamps: number[]
    metaTimestamps: number[]
    startMs: number
    endMs: number
}

export interface LoadBatch {
    sourceIndices: number[]
    reason: 'sequential' | 'seek_target' | 'seek_backward' | 'seek_gap_fill' | 'forward_from_seek' | 'backward_to_start'
}

export type Mode = { kind: 'sequential' } | { kind: 'seek'; targetTimestamp: number }
