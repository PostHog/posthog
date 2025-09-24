import { SessionRecordingSnapshotSource, SnapshotSourceType } from '~/types'

export type SourceKey = `${SnapshotSourceType}-${string}`
export const keyForSource = (source: SessionRecordingSnapshotSource): SourceKey => {
    // we should always have a blob_key, but in case we don't for some reason, fall back to source
    return `${source.source}-${source.blob_key || source.source}`
}
