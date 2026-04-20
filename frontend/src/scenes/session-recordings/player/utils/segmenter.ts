import { createSegments as _createSegments, mapSnapshotsToWindowId } from '@posthog/replay-shared'
import { eventWithTime } from '@posthog/rrweb-types'

import { Dayjs } from 'lib/dayjs'

import { RecordingSegment, RecordingSnapshot } from '~/types'

export { mapSnapshotsToWindowId }

export const createSegments = (
    snapshots: RecordingSnapshot[],
    start: Dayjs | null,
    end: Dayjs | null,
    trackedWindow: number | null | undefined,
    snapshotsByWindowId: Record<number, eventWithTime[]>
): RecordingSegment[] => {
    return _createSegments(
        snapshots,
        start?.valueOf() ?? null,
        end?.valueOf() ?? null,
        trackedWindow,
        snapshotsByWindowId
    )
}
