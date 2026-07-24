import { RecordingSnapshot, SessionRecordingSnapshotSource } from '../types'

export interface FullSnapshotRef {
    timestamp: number
    windowId: number
}

export interface SourceEntry {
    source: SessionRecordingSnapshotSource
    index: number
    state: 'unloaded' | 'fetched' | 'loaded'
    processedSnapshots: RecordingSnapshot[] | null
    fullSnapshots: FullSnapshotRef[]
    startMs: number
    endMs: number
}

export interface LoadBatch {
    sourceIndices: number[]
    reason: 'seek_target' | 'seek_backward' | 'seek_gap_fill' | 'seek_forward' | 'buffer_ahead' | 'load_all'
}

export interface SourceLoadingState {
    startMs: number
    endMs: number
    state: 'unloaded' | 'fetched' | 'loaded'
}
