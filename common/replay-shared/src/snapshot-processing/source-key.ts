import { SessionRecordingSnapshotSource, SnapshotSourceType } from '../types'

export type SourceKey = `${SnapshotSourceType}-${string}`
export const keyForSource = (source: SessionRecordingSnapshotSource): SourceKey => {
    return `${source.source}-${source.blob_key || source.source}`
}
