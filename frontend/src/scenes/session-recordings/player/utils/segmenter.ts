import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

import { Dayjs } from 'lib/dayjs'

import { RecordingSegment, RecordingSnapshot } from '~/types'

/**
 * This file is copied into the plugin server to calculate activeMilliseconds on ingestion
 * plugin-server/src/main/ingestion-queues/session-recording/snapshot-segmenter.ts
 *
 * Changes here should be reflected there
 * TODO add code sharing between plugin-server and front-end so that this duplication is unnecessary
 */

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

const ACTIVITY_THRESHOLD_MS = 5000

const isActiveEvent = (event: eventWithTime): boolean => {
    return (
        event.type === EventType.FullSnapshot ||
        event.type === EventType.Meta ||
        (event.type === EventType.IncrementalSnapshot && activeSources.includes(event.data?.source))
    )
}

export const mapSnapshotsToWindowId = (snapshots: RecordingSnapshot[]): Record<string, eventWithTime[]> => {
    const snapshotsByWindowId: Record<string, eventWithTime[]> = {}
    snapshots.forEach((snapshot) => {
        if (!snapshotsByWindowId[snapshot.windowId]) {
            snapshotsByWindowId[snapshot.windowId] = []
        }
        snapshotsByWindowId[snapshot.windowId].push(snapshot)
    })

    return snapshotsByWindowId
}

export const createSegments = (
    snapshots: RecordingSnapshot[],
    start: Dayjs | null,
    end: Dayjs | null,
    trackedWindow: string | null | undefined,
    snapshotsByWindowId: Record<string, eventWithTime[]>
): RecordingSegment[] => {
    let segments: RecordingSegment[] = []
    let activeSegment!: Partial<RecordingSegment>
    let lastActiveEventTimestamp = 0

    snapshots.forEach((snapshot, index) => {
        const eventIsActive = isActiveEvent(snapshot)
        const previousSnapshot = snapshots[index - 1]
        const isPreviousSnapshotLastForWindow =
            snapshotsByWindowId[previousSnapshot?.windowId]?.slice(-1)[0] === previousSnapshot

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
        if (activeSegment?.windowId !== snapshot.windowId && eventIsActive) {
            isNewSegment = true
        }

        // 5. If there are no more snapshots for this windowId
        if (isPreviousSnapshotLastForWindow) {
            isNewSegment = true
        }

        // NOTE: We have to make sure that we set this _after_ we use it
        lastActiveEventTimestamp = eventIsActive ? snapshot.timestamp : lastActiveEventTimestamp

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
    // To account for this we build up a new segment list filling in gaps with
    // either the tracked window if the viewing window is fixed
    // or whatever window is available (preferably the previous one)
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
        const list = [...acc]

        if (previousSegment && segment.startTimestamp !== previousSegment.endTimestamp) {
            // If the segments do not immediately follow each other, then we add a "gap" segment
            const startTimestamp = previousSegment.endTimestamp
            const endTimestamp = segment.startTimestamp
            // Offset the window ID check so we look for a subsequent segment
            const windowId = findWindowIdForTimestamp(startTimestamp + 1, trackedWindow || previousSegment.windowId)
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
                isActive: false,
            } as RecordingSegment)
        }

        // if the first segment starts after the start of the session, add a gap segment at the beginning
        const firstTimestamp = segments[0]?.startTimestamp
        if (firstTimestamp && firstTimestamp > start.valueOf()) {
            segments.unshift({
                kind: 'gap',
                startTimestamp: start.valueOf(),
                endTimestamp: firstTimestamp,
                isActive: false,
            } as RecordingSegment)
        }
    }

    segments = segments.map((segment) => {
        // These can all be done in a loop at the end...
        segment.durationMs = segment.endTimestamp - segment.startTimestamp
        return segment
    })

    return segments
}
