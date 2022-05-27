import { StatsD } from 'hot-shots'
import { DateTime } from 'luxon'

import { connectObjectStorage, ObjectStorage } from '../../../src/main/services/objectStorage'
import { TimestampFormat } from '../../../src/types'
import { castTimestampOrNow } from '../../../src/utils/utils'
import { processSnapshotData } from '../../../src/worker/ingestion/session-recordings'

describe('processSnapshotData()', () => {
    let statsdTiming: jest.Mock
    let statsdIncrement: jest.Mock
    let statsd: StatsD
    let theSnapshotEvent: Record<any, any>

    beforeEach(() => {
        theSnapshotEvent = { data: 'tomato' }
        statsdTiming = jest.fn()
        statsdIncrement = jest.fn()
        statsd = { timing: statsdTiming, increment: statsdIncrement } as unknown as StatsD
    })

    const processWithTestContext = async (
        snapshotData: Record<any, any>,
        objectStorage: ObjectStorage,
        teamId = 4,
        timestamp: DateTime = DateTime.now()
    ) => await processSnapshotData(timestamp, '123456', '7890', snapshotData, teamId, objectStorage, statsd)

    it('returns stringified data when storage is disabled', async () => {
        const actual = await processWithTestContext(
            theSnapshotEvent,
            connectObjectStorage({ OBJECT_STORAGE_ENABLED: false })
        )
        expect(actual).toEqual(JSON.stringify(theSnapshotEvent))
        expect(statsdTiming).toHaveBeenCalledTimes(0)
        expect(statsdIncrement).toHaveBeenCalledTimes(0)
    })

    it('returns stringified data when the team is not on the allow list', async () => {
        const actual = await processWithTestContext(
            theSnapshotEvent,
            connectObjectStorage({
                OBJECT_STORAGE_ENABLED: true,
                OBJECT_STORAGE_SESSION_RECORDING_ENABLED_TEAMS: '1,2,3,4',
            }),
            5,
            DateTime.now()
        )

        expect(actual).toEqual(JSON.stringify(theSnapshotEvent))
        expect(statsdTiming).toHaveBeenCalledTimes(0)
        expect(statsdIncrement).toHaveBeenCalledTimes(0)
    })

    it('returns stringified data when put object fails', async () => {
        const objectStorage: ObjectStorage = {
            healthcheck: () => Promise.resolve(true),
            isEnabled: true,
            putObject: () => {
                throw new Error('force an error')
            },
            sessionRecordingAllowList: [4],
        }

        const actual = await processWithTestContext(theSnapshotEvent, objectStorage)

        expect(actual).toEqual(JSON.stringify(theSnapshotEvent))
        expect(statsdTiming).toHaveBeenCalledTimes(1)
        expect(statsdIncrement).toHaveBeenCalledTimes(1)
        expect(statsdIncrement).toHaveBeenCalledWith('session_data.storage_upload.error', {
            session_id: '123456',
            team_id: '4',
        })
    })

    it('returns altered data when it can store session data in object storage', async () => {
        const objectStorage: ObjectStorage = {
            healthcheck: () => Promise.resolve(true),
            isEnabled: true,
            putObject: () => Promise.resolve(),
            sessionRecordingAllowList: [4],
        }

        theSnapshotEvent = { data: 'tomato', chunk_id: 1, chunk_index: 1 }
        const now = DateTime.now()
        const actual = await processWithTestContext(theSnapshotEvent, objectStorage, 4, now)

        const expectedFolderDate = castTimestampOrNow(now, TimestampFormat.DateOnly)
        const expectedOrderingTimestamp = castTimestampOrNow(now, TimestampFormat.UnixMilliseconds)
        expect(actual).toEqual(
            JSON.stringify({
                data: 'tomato',
                chunk_id: 1,
                chunk_index: 1,
                object_storage_path: [
                    'session_recordings',
                    expectedFolderDate,
                    4,
                    '123456',
                    '7890',
                    `${expectedOrderingTimestamp}-1`,
                    1,
                ].join('/'),
            })
        )
        expect(statsdTiming).toHaveBeenCalledTimes(1)
        expect(statsdIncrement).toHaveBeenCalledTimes(1)
        expect(statsdIncrement).toHaveBeenCalledWith('session_data.storage_upload.success', {
            session_id: '123456',
            team_id: '4',
        })
    })
})
