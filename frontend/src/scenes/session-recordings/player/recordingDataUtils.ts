import {
    PlayerPosition,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingStartAndEndTime,
    SessionPlayerSnapshotData,
    SessionRecordingMeta,
    SessionRecordingType,
} from '~/types'
import { sum } from 'lib/utils'
import { dayjs } from 'lib/dayjs'

export const IS_TEST_MODE = process.env.NODE_ENV === 'test'
export const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

export function generateInactiveSegmentsForRange(
    rangeStartTime: number,
    rangeEndTime: number,
    lastActiveWindowId: string,
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime>,
    isFirstSegment: boolean = false,
    isLastSegment: boolean = false
): RecordingSegment[] {
    // Given the start and end times of a known period of inactivity,
    // this function will try to create recording segments to fill the gap based on the
    // start and end times of the given window_ids
    const sortedWindows = Object.entries(startAndEndTimesByWindowId).slice()
    sortedWindows.sort(([, a], [, b]) => a.startTimeEpochMs - b.startTimeEpochMs)

    // Order of window_ids to use for generating inactive segments. Start with the window_id of the
    // last active segment, then try the other window_ids in order of start_time
    const windowIdPriorityList = [lastActiveWindowId, ...sortedWindows.map(([windowId]) => windowId)]
    let inactiveSegments: RecordingSegment[] = []
    let currentTime = rangeStartTime

    windowIdPriorityList.forEach((windowId) => {
        const windowStartTime = startAndEndTimesByWindowId[windowId].startTimeEpochMs
        const windowEndTime = startAndEndTimesByWindowId[windowId].endTimeEpochMs
        if (windowEndTime > currentTime && currentTime < rangeEndTime) {
            // Add/subtract a millisecond to make sure the segments don't exactly overlap
            const segmentStartTime = Math.max(windowStartTime, currentTime)
            const segmentEndTime = Math.min(windowEndTime, rangeEndTime)
            inactiveSegments.push({
                startPlayerPosition: {
                    windowId,
                    time: segmentStartTime - windowStartTime,
                },
                endPlayerPosition: {
                    windowId,
                    time: segmentEndTime - windowStartTime,
                },
                durationMs: segmentEndTime - segmentStartTime,
                startTimeEpochMs: segmentStartTime,
                endTimeEpochMs: segmentEndTime,
                windowId,
                isActive: false,
            })
            currentTime = Math.min(segmentEndTime, windowEndTime)
        }
    })

    // Ensure segments don't exactly overlap. This makes the corresponding player logic simpler
    inactiveSegments = inactiveSegments.map((segment, index) => ({
        ...segment,
        startTimeEpochMs:
            segment.startTimeEpochMs +
            Number(
                (index === 0 && segment.startTimeEpochMs === rangeStartTime && !isFirstSegment) ||
                    (index > 0 && segment.startTimeEpochMs === inactiveSegments[index - 1].endTimeEpochMs)
            ),
        endTimeEpochMs:
            segment.endTimeEpochMs -
            Number(index === inactiveSegments.length - 1 && segment.endTimeEpochMs === rangeEndTime && !isLastSegment),
    }))

    return inactiveSegments
}

export function parseStartAndEndTimesByWindowId(
    startAndEndTimesByWindowId: SessionRecordingType['start_and_end_times_by_window_id']
): Record<string, RecordingStartAndEndTime> {
    const computedStartAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime> = {}
    Object.entries(startAndEndTimesByWindowId || {}).forEach(([windowId, startAndEndTimes]) => {
        computedStartAndEndTimesByWindowId[windowId] = {
            startTimeEpochMs: +dayjs(startAndEndTimes.start_time),
            endTimeEpochMs: +dayjs(startAndEndTimes.end_time),
        }
    })
    return computedStartAndEndTimesByWindowId
}

export function parseSegments(
    incomingSegments: SessionRecordingType['segments'] = [],
    prevSegments: RecordingSegment[] = [],
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime>
): RecordingSegment[] {
    // Transform into list of RecordingSegments
    const segments: RecordingSegment[] = [
        ...(prevSegments ?? []),
        ...(incomingSegments?.map((segment): RecordingSegment => {
            const windowStartTime = startAndEndTimesByWindowId?.[segment.window_id]?.startTimeEpochMs
            const startTimeEpochMs = +dayjs(segment?.start_time)
            const endTimeEpochMs = +dayjs(segment?.end_time)
            const startPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: startTimeEpochMs - windowStartTime,
            }
            const endPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: endTimeEpochMs - windowStartTime,
            }
            const durationMs = endTimeEpochMs - startTimeEpochMs
            return {
                startPlayerPosition,
                endPlayerPosition,
                durationMs,
                startTimeEpochMs,
                endTimeEpochMs,
                windowId: segment.window_id,
                isActive: segment.is_active,
            }
        }) || []),
    ]

    segments.sort((a, b) => a.startTimeEpochMs - b.endTimeEpochMs)

    // Now that segments are incrementally loaded by snapshots, it is important to keep them in order as they come in.
    // We also offload filling in the gaps between the active segments with inactive segments to the frontend.
    let allSegments: RecordingSegment[] = []
    const activeSegments = segments.slice()
    const firstStartTime = Math.min(
        ...Object.values(startAndEndTimesByWindowId).map(({ startTimeEpochMs }) => startTimeEpochMs)
    )
    const lastEndTime = Math.max(
        ...Object.values(startAndEndTimesByWindowId).map(({ endTimeEpochMs }) => endTimeEpochMs)
    )
    let currentTimestamp = firstStartTime
    let currentWindowId = Object.entries(startAndEndTimesByWindowId).filter(
        ([, { startTimeEpochMs }]) => startTimeEpochMs === firstStartTime
    )[0][0]

    activeSegments.forEach((segment, index) => {
        // It's possible that segments overlap and we don't need to fill a gap
        if (segment.startTimeEpochMs > currentTimestamp) {
            allSegments = [
                ...allSegments,
                ...generateInactiveSegmentsForRange(
                    currentTimestamp,
                    segment.startTimeEpochMs,
                    currentWindowId,
                    startAndEndTimesByWindowId,
                    index === 0
                ),
            ]
        }
        allSegments.push(segment)
        currentWindowId = segment.windowId
        currentTimestamp = Math.max(segment.endTimeEpochMs, currentTimestamp)
    })

    // If the last segment ends before the recording ends, we need to fill in the gap
    if (currentTimestamp < lastEndTime) {
        allSegments = [
            ...allSegments,
            ...generateInactiveSegmentsForRange(
                currentTimestamp,
                lastEndTime,
                currentWindowId,
                startAndEndTimesByWindowId,
                currentTimestamp === firstStartTime,
                true
            ),
        ]
    }

    return allSegments
}

export const parseMetadataResponse = (recording: SessionRecordingType): SessionRecordingMeta => {
    const startAndEndTimesByWindowId = parseStartAndEndTimesByWindowId(recording.start_and_end_times_by_window_id)
    return {
        startAndEndTimesByWindowId,
        pinnedCount: recording.pinned_count ?? 0,
    }
}

// TODO: Write tests for this
export const parseSnapshotResponse = (
    recording: Pick<SessionRecordingType, 'snapshot_data_by_window_id' | 'segments'>,
    prevSnapshotData: SessionPlayerSnapshotData | null,
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime>
): SessionPlayerSnapshotData => {
    // If we have a next url, we need to append the new snapshots to the existing ones
    const snapshotsByWindowId = {
        ...(prevSnapshotData?.snapshotsByWindowId ?? {}),
    }
    // We merge the new snapshots with the existing ones and sort by timestamp to ensure they are in order
    Object.entries(recording.snapshot_data_by_window_id ?? {}).forEach(([windowId, snapshots]) => {
        if (!(windowId in snapshotsByWindowId)) {
            snapshotsByWindowId[windowId] = {
                events_summary: [],
                snapshot_data: [],
            }
        }
        snapshotsByWindowId[windowId]['events_summary'] = [
            ...snapshotsByWindowId[windowId]['events_summary'],
            ...snapshots['events_summary'],
        ].sort((a, b) => a.timestamp - b.timestamp)
        snapshotsByWindowId[windowId]['snapshot_data'] = [
            ...snapshotsByWindowId[windowId]['snapshot_data'],
            ...snapshots['snapshot_data'],
        ].sort((a, b) => a.timestamp - b.timestamp)
    })

    // Remove inactive segments and reparse all together in the case where there are more snapshots to load.
    const previousSegments = prevSnapshotData?.segments?.filter(({ isActive }) => !!isActive) ?? []
    const segments = parseSegments(recording.segments, previousSegments, startAndEndTimesByWindowId)

    return {
        ...prevSnapshotData,
        segments,
        startAndEndTimesByWindowId,
        snapshotsByWindowId,
        recordingDurationMs: sum(segments.map((s) => s.durationMs)),
    }
}
export const generateRecordingReportDurations = (
    cache: Record<string, any>,
    values: Record<string, any>
): RecordingReportLoadTimes => {
    return {
        metadata: {
            size: (values.sessionPlayerMetaData.segments ?? []).length,
            duration: Math.round(performance.now() - cache.metaStartTime),
        },
        snapshots: {
            size: Object.keys(values.sessionPlayerSnapshotData?.snapshotsByWindowId ?? {}).length,
            duration: Math.round(performance.now() - cache.snapshotsStartTime),
        },
        events: {
            size: values.sessionEventsData?.events?.length ?? 0,
            duration: Math.round(performance.now() - cache.eventsStartTime),
        },
        performanceEvents: {
            size: values.performanceEvents?.length ?? 0,
            duration: Math.round(performance.now() - cache.performanceEventsStartTime),
        },
        firstPaint: cache.firstPaintDurationRow,
    }
}

// Returns the maximum player position that the recording has been buffered to.
// Data can be received out of order (e.g. events from a later segment are received
// before events from an earlier segment). So this function iterates through the
// segments in their order and returns when it first detects data is not loaded.
export const calculateBufferedTo = (snapshots: SessionPlayerSnapshotData): PlayerPosition | null => {
    let bufferedTo: PlayerPosition | null = null
    // If we don't have metadata or snapshots yet, then we can't calculate the bufferedTo.
    if (!snapshots.segments || !snapshots.snapshotsByWindowId || !snapshots.startAndEndTimesByWindowId) {
        return bufferedTo
    }

    snapshots.segments.forEach((segment) => {
        const lastEventForWindowId = (snapshots.snapshotsByWindowId[segment.windowId]?.['snapshot_data'] ?? [])
            .slice(-1)
            .pop()

        if (
            lastEventForWindowId &&
            lastEventForWindowId.timestamp >= segment.startTimeEpochMs &&
            snapshots.startAndEndTimesByWindowId
        ) {
            // If we've buffered past the start of the segment, see how far.
            const windowStartTime = snapshots.startAndEndTimesByWindowId[segment.windowId].startTimeEpochMs
            bufferedTo = {
                windowId: segment.windowId,
                time: Math.min(lastEventForWindowId.timestamp - windowStartTime, segment.endPlayerPosition.time),
            }
        }
    })

    return bufferedTo
}
