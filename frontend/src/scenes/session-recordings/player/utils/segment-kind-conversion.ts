import { RecordingSegment } from '~/types'

import { SnapshotStore } from '../snapshot-store/SnapshotStore'

export function convertSegmentKinds(
    segments: RecordingSegment[],
    snapshotStore: SnapshotStore,
    isLoadingSnapshots: boolean
): RecordingSegment[] {
    return segments.map((segment) => {
        if (snapshotStore.sourceCount > 0) {
            const startIdx = snapshotStore.getSourceIndexForTimestamp(segment.startTimestamp)
            const endIdx = snapshotStore.getSourceIndexForTimestamp(segment.endTimestamp)
            const hasUnloaded = snapshotStore.getUnloadedIndicesInRange(startIdx, endIdx).length > 0

            if (segment.kind === 'buffer' && !hasUnloaded) {
                // All sources covering this buffer range are already loaded —
                // the data isn't pending, it's a gap with no events.
                return { ...segment, kind: 'gap' as const }
            }

            if (segment.kind === 'gap' && hasUnloaded) {
                // This looks like a gap but has unloaded sources — it's actually
                // a region where data hasn't been fetched yet. Convert to buffer
                // so the player pauses and waits for data instead of skipping.
                return { ...segment, kind: 'buffer' as const, isLoading: isLoadingSnapshots }
            }
        }

        if (segment.kind === 'buffer') {
            return {
                ...segment,
                isLoading: isLoadingSnapshots,
            }
        }
        return segment
    })
}
