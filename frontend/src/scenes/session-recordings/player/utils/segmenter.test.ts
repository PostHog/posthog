import { dayjs } from 'lib/dayjs'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import {
    convertSnapshotsResponse,
    sortedRecordingSnapshots,
} from 'scenes/session-recordings/__mocks__/recording_snapshots'

import { RecordingSnapshot } from '~/types'

import { createSegments, mapSnapshotsToWindowId } from './segmenter'

describe('segmenter', () => {
    it('matches snapshots', () => {
        const snapshots = convertSnapshotsResponse(sortedRecordingSnapshots().snapshot_data_by_window_id)
        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(
            snapshots,
            dayjs(recordingMetaJson.start_time),
            dayjs(recordingMetaJson.end_time),
            null,
            snapshotsByWindowId
        )

        expect(segments).toMatchSnapshot()
    })

    it('segments a default buffer based on start and end', () => {
        const segments = createSegments(
            [],
            dayjs('2023-01-01T00:00:00.000Z'),
            dayjs('2023-01-01T00:10:00.000Z'),
            null,
            {}
        )

        expect(segments).toEqual([
            {
                durationMs: 600000,
                endTimestamp: 1672531800000,
                isActive: false,
                kind: 'buffer',
                startTimestamp: 1672531200000,
            },
        ])
    })

    it('inserts gaps inclusively', () => {
        // NOTE: It is important that the segments are "inclusive" of the start and end timestamps as the player logic
        // depends on this to choose which segment should be played next
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 3, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 3, data: {} } as any,
            { windowId: 2, timestamp: end.valueOf() - 100, type: 3, data: {} } as any,
            { windowId: 2, timestamp: end.valueOf(), type: 3, data: {} } as any,
        ]

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, null, snapshotsByWindowId)

        expect(segments).toMatchSnapshot()
    })

    it('includes inactive events in the active segment until a threshold', () => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 3, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 6, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 4000, type: 6, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 6000, type: 3, data: {} } as any,
            { windowId: 1, timestamp: end.valueOf(), type: 3, data: {} } as any,
        ]

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, null, snapshotsByWindowId)

        expect(segments).toMatchSnapshot()
    })

    // A gap is filled from whichever window covers it, so an unusable window id must not reach the lookup
    it.each([
        {
            name: 'the tracked window has no loaded snapshots',
            trackedWindow: 99,
            windowIds: [1, 1, 2, 2],
        },
        {
            name: 'a snapshot has no window id',
            trackedWindow: null,
            windowIds: [undefined, 1, 1, 1],
        },
    ])('fills a gap when $name', ({ trackedWindow, windowIds }) => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')
        const timestamps = [start.valueOf(), start.valueOf() + 100, end.valueOf() - 100, end.valueOf()]

        const snapshots: RecordingSnapshot[] = timestamps.map(
            (timestamp, index) => ({ windowId: windowIds[index], timestamp, type: 3, data: {} }) as any
        )

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, trackedWindow, snapshotsByWindowId)

        const loadedWindowIds = windowIds.filter((id) => id !== undefined)
        expect(segments.filter((segment) => segment.kind === 'gap')).not.toHaveLength(0)
        expect(
            segments.filter((segment) => segment.windowId !== undefined && !loadedWindowIds.includes(segment.windowId))
        ).toEqual([])
    })

    it('ends a segment if it is the last window', () => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = start.add(1000, 'milliseconds')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 2, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 3, data: {} } as any,
            { windowId: 2, timestamp: start.valueOf() + 500, type: 3, data: {} } as any,
            { windowId: 2, timestamp: end, type: 3, data: {} } as any,
        ]

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, null, snapshotsByWindowId)

        expect(segments).toMatchSnapshot()
    })
})
