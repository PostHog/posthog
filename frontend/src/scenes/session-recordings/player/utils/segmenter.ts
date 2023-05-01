import { EventType, IncrementalSource, eventWithTime } from '@rrweb/types'
import { Dayjs } from 'lib/dayjs'
import { RecordingSegment, SessionPlayerSnapshotData } from '~/types'

const activeSources = [
    IncrementalSource.MouseMove,
    IncrementalSource.MouseInteraction,
    IncrementalSource.Scroll,
    IncrementalSource.ViewportResize,
    IncrementalSource.Input,
    IncrementalSource.TouchMove,
    IncrementalSource.MediaInteraction,
    IncrementalSource.Drag,
]

const ACTIVITY_THRESHOLD_MS = 5_000

const isActiveEvent = (event: eventWithTime): boolean => {
    return event.type === EventType.IncrementalSnapshot && activeSources.includes(event.data?.source)
}

export const createSegments = (
    sessionPlayerSnapshotData: SessionPlayerSnapshotData | null,
    snapshotsByWindowId: Record<string, eventWithTime[]>,
    start?: Dayjs,
    end?: Dayjs
): RecordingSegment[] => {
    let segments: RecordingSegment[] = []
    let activeSegment!: Partial<RecordingSegment>
    let lastActiveEventTimestamp = 0

    sessionPlayerSnapshotData?.snapshots.forEach((snapshot) => {
        const eventIsActive = isActiveEvent(snapshot)
        lastActiveEventTimestamp = eventIsActive ? snapshot.timestamp : lastActiveEventTimestamp

        // When do we create a new segment?
        // 1. If we don't have one yet
        let isNewSegment = !activeSegment

        // 2. If it is currently inactive but a new "active" event comes in
        if (eventIsActive && !activeSegment?.isActive) {
            isNewSegment = true
        }

        // 3. If it is currently active but no new active event has been seen for the activity threshold
        if (activeSegment?.isActive && lastActiveEventTimestamp + ACTIVITY_THRESHOLD_MS < snapshot.timestamp) {
            isNewSegment = true
        }

        // 4. If windowId changes we create a new segment
        if (activeSegment?.windowId !== snapshot.windowId) {
            isNewSegment = true
        }

        if (isNewSegment) {
            if (activeSegment) {
                segments.push(activeSegment as RecordingSegment)
            }

            activeSegment = {
                kind: 'window',
                startTimestamp: snapshot.timestamp,
                windowId: snapshot.windowId,
                isActive: eventIsActive,
            }
        }

        activeSegment.endTimestamp = snapshot.timestamp
    })

    if (activeSegment) {
        segments.push(activeSegment as RecordingSegment)
    }

    // We've built the segments, but this might not account for "gaps" in them
    // To account for this we build up a new segment list filling in gaps with the whatever window is available (preferably the previous one)
    // Or a "null" window if there is nothing (like if they navigated away to a different site)

    const findWindowIdForTimestamp = (timestamp: number, preferredWindowId?: string): string | undefined => {
        // Check all the snapshotsByWindowId to see if the timestamp is within its range
        // prefer the preferredWindowId if it is within its range
        let windowIds = Object.keys(snapshotsByWindowId)

        if (preferredWindowId) {
            windowIds = [preferredWindowId, ...windowIds.filter((id) => id !== preferredWindowId)]
        }

        for (const windowId of windowIds) {
            const snapshots = snapshotsByWindowId[windowId]
            if (snapshots[0].timestamp <= timestamp && snapshots[snapshots.length - 1].timestamp >= timestamp) {
                return windowId
            }
        }
    }

    segments = segments.reduce((acc, segment, index) => {
        const previousSegment = segments[index - 1]
        const nextSegment = segments[index + 1]
        const list = [...acc]

        if (previousSegment && nextSegment && segment.startTimestamp - previousSegment.endTimestamp > 1) {
            const startTimestamp = previousSegment.endTimestamp + 1
            const endTimestamp = segment.startTimestamp - 1
            const windowId = findWindowIdForTimestamp(startTimestamp, previousSegment.windowId)
            const gapSegment: Partial<RecordingSegment> = {
                kind: 'gap',
                startTimestamp,
                endTimestamp,
                windowId,
                isActive: false,
            }

            list.push(gapSegment as RecordingSegment)
        }

        list.push(segment)

        return list
    }, [] as RecordingSegment[])

    if (start && end) {
        // As we don't necessarily have all the segments at once, we add a final segment to fill the gap between the last segment and the end of the recording
        const latestTimestamp = segments[segments.length - 1]?.endTimestamp
        const endTimestamp = end.valueOf()

        if (!latestTimestamp || latestTimestamp < endTimestamp) {
            segments.push({
                kind: 'buffer',
                startTimestamp: latestTimestamp ? latestTimestamp + 1 : start.valueOf(),
                endTimestamp: endTimestamp,
                windowId: 'buffer',
                isActive: false,
            } as RecordingSegment)
        }
    }

    segments = segments.map((segment) => {
        // These can all be done in a loop at the end...
        segment.durationMs = segment.endTimestamp - segment.startTimestamp
        return segment
    })

    console.log({ segments })

    // segments.forEach((segment) => {
    //     console.log('segment', {
    //         start: segment.startTimeEpochMs - segments[0].startTimeEpochMs,
    //         end: segment.endTimeEpochMs - segments[0].startTimeEpochMs,
    //         active: segment.isActive,
    //         windowId: segment.windowId,
    //         startTimestamp: segment.startTimeEpochMs,
    //     })
    // })

    return segments
}
