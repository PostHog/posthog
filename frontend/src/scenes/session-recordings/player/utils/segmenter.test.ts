import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import { createSegments } from './segmenter'
import { convertSnapshotsResponse } from '../sessionRecordingDataLogic'
import { dayjs } from 'lib/dayjs'
import { RecordingSnapshot } from '~/types'

describe('segmenter', () => {
    it('matches snapshots', async () => {
        const snapshots = convertSnapshotsResponse(recordingSnapshotsJson.snapshot_data_by_window_id)
        const segments = createSegments(
            snapshots,
            dayjs(recordingMetaJson.start_time),
            dayjs(recordingMetaJson.end_time)
        )

        expect(segments).toMatchSnapshot()
    })

    it('segments a default buffer based on start and end', () => {
        const segments = createSegments([], dayjs('2023-01-01T00:00:00.000Z'), dayjs('2023-01-01T00:10:00.000Z'))

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

    it('inserts gaps', () => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 'A', timestamp: start.valueOf(), type: 3, data: {} } as any,
            { windowId: 'A', timestamp: start.valueOf() + 100, type: 3, data: {} } as any,
            { windowId: 'B', timestamp: end.valueOf() - 100, type: 3, data: {} } as any,
            { windowId: 'B', timestamp: end.valueOf(), type: 3, data: {} } as any,
        ]

        const segments = createSegments(snapshots, start, end)

        expect(segments).toEqual([
            {
                kind: 'window',
                startTimestamp: 1672531200000,
                windowId: 'A',
                isActive: true,
                endTimestamp: 1672531200100,
                durationMs: 100,
            },
            {
                durationMs: 599798,
                endTimestamp: 1672531799899,
                isActive: false,
                kind: 'gap',
                startTimestamp: 1672531200101,
                windowId: undefined,
            },
            {
                kind: 'window',
                startTimestamp: 1672531799900,
                windowId: 'B',
                isActive: false,
                endTimestamp: 1672531800000,
                durationMs: 100,
            },
        ])
    })

    it('includes inactive events in the active segment until a threshold', () => {
        const start = dayjs('2023-01-01T00:00:00.000Z')
        const end = dayjs('2023-01-01T00:10:00.000Z')

        const snapshots: RecordingSnapshot[] = [
            { windowId: 'A', timestamp: start.valueOf(), type: 3, data: {} } as any,
            { windowId: 'A', timestamp: start.valueOf() + 100, type: 6, data: {} } as any,
            { windowId: 'A', timestamp: start.valueOf() + 4000, type: 6, data: {} } as any,
            { windowId: 'A', timestamp: start.valueOf() + 6000, type: 3, data: {} } as any,
            { windowId: 'A', timestamp: end.valueOf(), type: 3, data: {} } as any,
        ]

        const segments = createSegments(snapshots, start, end)

        expect(segments).toEqual([
            {
                kind: 'window',
                startTimestamp: start.valueOf(),
                windowId: 'A',
                isActive: true,
                endTimestamp: start.valueOf() + 4000,
                durationMs: 4000,
            },
            {
                kind: 'gap',
                startTimestamp: start.valueOf() + 4000 + 1,
                endTimestamp: start.valueOf() + 6000 - 1,
                windowId: 'A',
                isActive: false,
                durationMs: 1998,
            },
            {
                kind: 'window',
                startTimestamp: start.valueOf() + 6000,
                windowId: 'A',
                isActive: false,
                endTimestamp: end.valueOf(),
                durationMs: 594000,
            },
        ])
    })
})
