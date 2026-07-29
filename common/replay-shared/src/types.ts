import { eventWithTime } from 'posthog-js/rrweb-types'

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
    /**
     * Position in the order the snapshot was parsed out of the ingested blobs, i.e. capture order.
     * rrweb applies mutations by node id and last write wins, so two events in the same millisecond
     * must stay in capture order or a later text value can be overwritten by an earlier one.
     * Timestamps alone cannot express that, so this is the tiebreaker. Absent on snapshots we
     * synthesize during processing, which sort by their insertion position instead.
     */
    seq?: number
    /** Set on every event split out of one oversized mutation by chunkMutationSnapshot. */
    isMutationChunk?: boolean
}
