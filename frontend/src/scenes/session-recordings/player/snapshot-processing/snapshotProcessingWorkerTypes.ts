import type { EncodedRecordingSnapshot, RecordingSnapshot } from '~/types'

export type ParseSnapshotsRequest = {
    type: 'parse-snapshots'
    id: string
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array
    sessionId: string
}

export type ParseSnapshotsResponse = {
    type: 'parse-snapshots-response'
    id: string
    snapshots: RecordingSnapshot[]
    error?: string
}

export type WorkerRequest = ParseSnapshotsRequest

export type WorkerResponse = ParseSnapshotsResponse

export type WorkerError = {
    type: 'error'
    id: string
    error: string
}
