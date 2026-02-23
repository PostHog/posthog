import { eventWithTime } from '@posthog/rrweb-types'

import { dayjs } from 'lib/dayjs'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import {
    convertSnapshotsResponse,
    sortedRecordingSnapshots,
} from 'scenes/session-recordings/__mocks__/recording_snapshots'

import { RecordingSnapshot } from '~/types'

import { createSegments } from './segmenter'

function groupByWindowId(snapshots: RecordingSnapshot[]): Record<number, eventWithTime[]> {
    const result: Record<number, eventWithTime[]> = {}
    for (const snapshot of snapshots) {
        if (!result[snapshot.windowId]) {
            result[snapshot.windowId] = []
        }
        result[snapshot.windowId].push(snapshot)
    }
    return result
}

describe('segmenter', () => {
    it('matches snapshots', () => {
        const snapshots = convertSnapshotsResponse(sortedRecordingSnapshots().snapshot_data_by_window_id)
        const segments = createSegments(
            snapshots,
            dayjs(recordingMetaJson.start_time),
            dayjs(recordingMetaJson.end_time),
            null,
            groupByWindowId(snapshots)
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
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 1, timestamp: start.valueOf(), type: 3, data: {} } as any,
            { windowId: 1, timestamp: start.valueOf() + 100, type: 3, data: {} } as any,
            { windowId: 2, timestamp: end.valueOf() - 100, type: 3, data: {} } as any,
            { windowId: 2, timestamp: end.valueOf(), type: 3, data: {} } as any,
        ]

        const segments = createSegments(snapshots, start, end, null, groupByWindowId(snapshots))

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

        const segments = createSegments(snapshots, start, end, null, groupByWindowId(snapshots))

        expect(segments).toMatchSnapshot()
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

        const segments = createSegments(snapshots, start, end, null, groupByWindowId(snapshots))

        expect(segments).toMatchSnapshot()
    })
})
