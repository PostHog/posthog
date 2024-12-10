import { DateTime } from 'luxon'
import { HighLevelProducer } from 'node-rdkafka'

import { produce } from '../../../../../src/kafka/producer'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { ReplayEventsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/replay-events-ingester'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { TimestampFormat } from '../../../../../src/types'
import { status } from '../../../../../src/utils/status'
import { castTimestampOrNow } from '../../../../../src/utils/utils'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const makeIncomingMessage = (source: string | null, timestamp: number): IncomingRecordingMessage => {
    return {
        distinct_id: '',
        eventsRange: { start: timestamp, end: timestamp },
        eventsByWindowId: { '': [{ data: { any: 'thing' }, type: 2, timestamp: timestamp }] },
        metadata: {
            lowOffset: 0,
            highOffset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: timestamp,
            consoleLogIngestionEnabled: true,
            rawSize: 0,
        },
        session_id: '',
        team_id: 0,
        snapshot_source: source,
    }
}

describe('replay events ingester', () => {
    let ingester: ReplayEventsIngester
    const mockProducer: jest.Mock = jest.fn()

    beforeEach(() => {
        mockProducer.mockClear()
        mockProducer['connect'] = jest.fn()
        mockProducer['isConnected'] = () => true

        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        ingester = new ReplayEventsIngester(mockProducer as unknown as HighLevelProducer, mockedHighWaterMarker)
    })

    test('does not ingest messages from a month in the future', async () => {
        const now = DateTime.utc()
        const twoMonthsFromNow = now.plus({ months: 2 })
        const expectedDaysFromNow = twoMonthsFromNow.diff(now, 'days').days

        await ingester.consume(makeIncomingMessage("mickey's fun house", twoMonthsFromNow.toMillis()))

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(produce).mock.calls).toHaveLength(1)
        expect(jest.mocked(produce).mock.calls[0]).toHaveLength(1)
        const call = jest.mocked(produce).mock.calls[0][0]

        expect(call.topic).toEqual('clickhouse_ingestion_warnings_test')
        // call.value is a Buffer convert it to a string
        const value = call.value ? JSON.parse(call.value.toString()) : null
        const expectedTimestamp = castTimestampOrNow(twoMonthsFromNow, TimestampFormat.ClickHouse)

        expect(value.source).toEqual('plugin-server')
        expect(value.team_id).toEqual(0)
        expect(value.type).toEqual('replay_timestamp_too_far')
        const details = JSON.parse(value.details)
        expect(details).toEqual(
            expect.objectContaining({
                isValid: true,
                daysFromNow: expectedDaysFromNow,
                timestamp: expectedTimestamp,
            })
        )
    })

    test('it passes snapshot source along', async () => {
        const ts = new Date().getTime()
        await ingester.consume(makeIncomingMessage("mickey's fun house", ts))

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(produce).mock.calls).toHaveLength(1)
        expect(jest.mocked(produce).mock.calls[0]).toHaveLength(1)
        const call = jest.mocked(produce).mock.calls[0][0]
        expect(call.topic).toEqual('clickhouse_session_replay_events_test')
        // call.value is a Buffer convert it to a string
        const value = call.value ? JSON.parse(call.value.toString()) : null
        expect(value).toEqual({
            active_milliseconds: 0,
            click_count: 0,
            console_error_count: 0,
            console_log_count: 0,
            console_warn_count: 0,
            distinct_id: '',
            event_count: 1,
            first_timestamp: expect.any(String),
            first_url: null,
            keypress_count: 0,
            last_timestamp: expect.any(String),
            message_count: 1,
            mouse_activity_count: 0,
            session_id: '',
            size: 61,
            snapshot_source: "mickey's fun house",
            team_id: 0,
            uuid: expect.any(String),
        })
    })

    test('it defaults snapshot source to web when absent', async () => {
        const ts = new Date().getTime()
        await ingester.consume(makeIncomingMessage(null, ts))

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(produce).mock.calls).toHaveLength(1)
        expect(jest.mocked(produce).mock.calls[0]).toHaveLength(1)
        const call = jest.mocked(produce).mock.calls[0][0]
        expect(call.topic).toEqual('clickhouse_session_replay_events_test')
        // call.value is a Buffer convert it to a string
        const value = call.value ? JSON.parse(call.value.toString()) : null
        expect(value).toEqual({
            active_milliseconds: 0,
            click_count: 0,
            console_error_count: 0,
            console_log_count: 0,
            console_warn_count: 0,
            distinct_id: '',
            event_count: 1,
            first_timestamp: expect.any(String),
            first_url: null,
            keypress_count: 0,
            last_timestamp: expect.any(String),
            message_count: 1,
            mouse_activity_count: 0,
            session_id: '',
            size: 61,
            snapshot_source: 'web',
            team_id: 0,
            uuid: expect.any(String),
        })
    })
})
