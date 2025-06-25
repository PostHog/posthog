import { SessionRecordingSnapshotSource, SnapshotSourceType } from '~/types'

export type SourceKey = `${SnapshotSourceType}-${string}`
export const keyForSource = (source: SessionRecordingSnapshotSource): SourceKey => {
    // realtime sources vary, so blob_key is not always present and is either null or undefined...
    // we only care about a key when not realtime,
    // and we'll always have a key when not realtime
    return `${source.source}-${source.blob_key || source.source}`
}
