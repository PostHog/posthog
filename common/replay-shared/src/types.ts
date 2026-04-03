import { eventWithTime } from '@posthog/rrweb-types'

export interface RecordingSegment {
    kind: 'window' | 'buffer' | 'gap'
    startTimestamp: number
    endTimestamp: number
    durationMs: number
    windowId?: number
    isActive: boolean
    isLoading?: boolean
}

export type EncodedRecordingSnapshot = {
    windowId: number
    data: eventWithTime[]
}

export const SnapshotSourceType = {
    blob_v2: 'blob_v2',
    blob_v2_lts: 'blob_v2_lts',
    file: 'file',
} as const

export type SnapshotSourceType = (typeof SnapshotSourceType)[keyof typeof SnapshotSourceType]

export interface SessionRecordingSnapshotSource {
    source: SnapshotSourceType
    start_timestamp?: string
    end_timestamp?: string
    blob_key?: string
}

export interface SessionRecordingSnapshotSourceResponse {
    sources?: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'>[]
    snapshots?: RecordingSnapshot[]
    processed?: boolean
    sourceLoaded?: boolean
}

export type RecordingSnapshot = eventWithTime & {
    windowId: number
}
