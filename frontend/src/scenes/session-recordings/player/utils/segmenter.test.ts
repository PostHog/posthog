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

    it('keeps rendering the ongoing window while another window interleaves', () => {
        // Two tabs open at once interleave their snapshots by timestamp. Window 1 has coverage
        // through the end, so window 2's events must not take over the frame — otherwise a viewer
        // watching window 1 sees window 2 (e.g. a background marketing tab) flash into view.
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = start.add(300, 'milliseconds')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 2, data: {} } as any,
            { windowId: 2, timestamp: start.valueOf() + 50, type: 2, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 3, data: { source: 1 } } as any,
            { windowId: 2, timestamp: start.valueOf() + 150, type: 3, data: { source: 1 } } as any,
            { windowId: 1, timestamp: end.valueOf(), type: 3, data: { source: 1 } } as any,
        ]

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, null, snapshotsByWindowId)

        const renderedWindowIds = segments.filter((s) => s.kind === 'window').map((s) => s.windowId)
        expect(renderedWindowIds.length).toBeGreaterThan(0)
        expect(renderedWindowIds.every((windowId) => windowId === 1)).toBe(true)
    })

    it('hands the frame to a tracked window even while another window is ongoing', () => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = start.add(300, 'milliseconds')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 2, data: {} } as any,
            { windowId: 2, timestamp: start.valueOf() + 50, type: 2, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 3, data: { source: 1 } } as any,
            { windowId: 2, timestamp: start.valueOf() + 150, type: 3, data: { source: 1 } } as any,
            { windowId: 1, timestamp: end.valueOf(), type: 3, data: { source: 1 } } as any,
        ]

        const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
        const segments = createSegments(snapshots, start, end, 2, snapshotsByWindowId)

        expect(segments.filter((s) => s.kind === 'window').map((s) => s.windowId)).toContain(2)
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
