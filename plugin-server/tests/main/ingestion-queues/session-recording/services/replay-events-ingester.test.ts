import { DateTime } from 'luxon'

import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { ReplayEventsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/replay-events-ingester'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { TimestampFormat } from '../../../../../src/types'
import { status } from '../../../../../src/utils/status'
import { castTimestampOrNow } from '../../../../../src/utils/utils'

jest.mock('../../../../../src/utils/status')

import { getParsedQueuedMessages, mockProducer } from '../../../../helpers/mocks/producer.mock'

const makeIncomingMessage = (
    source: string | null,
    timestamp: number,
    extraWindowedEvents?: Record<string, Record<string, any>[]>
): IncomingRecordingMessage => {
    return {
        distinct_id: '',
        eventsRange: { start: timestamp, end: timestamp },
        eventsByWindowId: {
            '': [{ data: { any: 'thing' }, type: 2, timestamp: timestamp }],
            ...(extraWindowedEvents || {}),
        },
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

    beforeEach(() => {
        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        ingester = new ReplayEventsIngester(mockProducer, mockedHighWaterMarker)
    })

    test('does not ingest messages from a month in the future', async () => {
        const now = DateTime.utc()
        const twoMonthsFromNow = now.plus({ months: 2 })
        const expectedDaysFromNow = twoMonthsFromNow.diff(now, 'days').days

        await ingester.consume(makeIncomingMessage("mickey's fun house", twoMonthsFromNow.toMillis()))

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(mockProducer.queueMessages)).toHaveBeenCalledTimes(1)
        const topicMessages = getParsedQueuedMessages()
        expect(topicMessages).toHaveLength(1)
        expect(topicMessages[0].topic).toEqual('clickhouse_ingestion_warnings_test')
        const value = topicMessages[0].messages[0].value!
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
        expect(jest.mocked(mockProducer.queueMessages).mock.calls).toHaveLength(1)
        expect(jest.mocked(mockProducer.queueMessages).mock.calls[0]).toHaveLength(1)
        const topicMessages = getParsedQueuedMessages()
        expect(topicMessages).toHaveLength(1)
        expect(topicMessages[0].topic).toEqual('clickhouse_session_replay_events_test')
        // call.value is a Buffer convert it to a string
        const value = topicMessages[0].messages[0].value!
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
            urls: [],
        })
    })

    test('it defaults snapshot source to web when absent', async () => {
        const ts = new Date().getTime()
        await ingester.consume(makeIncomingMessage(null, ts))

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(mockProducer.queueMessages).mock.calls).toHaveLength(1)
        const topicMessages = getParsedQueuedMessages()
        expect(topicMessages).toHaveLength(1)
        expect(topicMessages[0].topic).toEqual('clickhouse_session_replay_events_test')
        const value = topicMessages[0].messages[0].value!
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
            urls: [],
        })
    })

    test('it adds URLs', async () => {
        const ts = new Date().getTime()
        await ingester.consume(
            makeIncomingMessage("mickey's fun house", ts, {
                anotherwindow: [
                    { data: { href: 'thing' }, type: 2, timestamp: ts },
                    // should be deduplicated
                    { data: { href: 'thing' }, type: 2, timestamp: ts },
                    { data: { href: 'thing2' }, type: 2, timestamp: ts },
                ],
            })
        )

        expect(jest.mocked(status.debug).mock.calls).toEqual([])
        expect(jest.mocked(mockProducer.queueMessages)).toHaveBeenCalledTimes(1)
        const topicMessages = getParsedQueuedMessages()
        expect(topicMessages).toHaveLength(1)
        expect(topicMessages[0].topic).toEqual('clickhouse_session_replay_events_test')
        const value = topicMessages[0].messages[0].value!
        expect(value).toEqual({
            active_milliseconds: 0,
            click_count: 0,
            console_error_count: 0,
            console_log_count: 0,
            console_warn_count: 0,
            distinct_id: '',
            event_count: 4,
            first_timestamp: expect.any(String),
            first_url: 'thing',
            keypress_count: 0,
            last_timestamp: expect.any(String),
            message_count: 1,
            mouse_activity_count: 0,
            session_id: '',
            size: 245,
            snapshot_source: "mickey's fun house",
            team_id: 0,
            uuid: expect.any(String),
            urls: ['thing', 'thing2'],
        })
    })
})
