import { HighLevelProducer } from 'node-rdkafka'

import { defaultConfig } from '../../../../../src/config/config'
import { createKafkaProducer, produce } from '../../../../../src/kafka/producer'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { ReplayEventsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/replay-events-ingester'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { PluginsServerConfig } from '../../../../../src/types'
import { status } from '../../../../../src/utils/status'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const makeIncomingMessage = (source: string | null, timestamp: number): IncomingRecordingMessage => {
    return {
        distinct_id: '',
        events: [{ data: { any: 'thing' }, type: 2, timestamp: timestamp }],
        metadata: {
            offset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: timestamp,
            consoleLogIngestionEnabled: true,
        },
        session_id: '',
        team_id: 0,
        snapshot_source: source,
    }
}

describe('replay events ingester', () => {
    let ingester: ReplayEventsIngester
    const mockProducer: jest.Mock = jest.fn()

    beforeEach(async () => {
        mockProducer.mockClear()
        mockProducer['connect'] = jest.fn()

        jest.mocked(createKafkaProducer).mockImplementation(() =>
            Promise.resolve(mockProducer as unknown as HighLevelProducer)
        )

        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        ingester = new ReplayEventsIngester({ ...defaultConfig } as PluginsServerConfig, mockedHighWaterMarker)
        await ingester.start()
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
