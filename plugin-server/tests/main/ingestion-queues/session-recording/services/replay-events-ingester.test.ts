import { DateTime } from 'luxon'

import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { ReplayEventsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/replay-events-ingester'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { TimestampFormat } from '../../../../../src/types'
import { parseJSON } from '../../../../../src/utils/json-parse'
import { castTimestampOrNow } from '../../../../../src/utils/utils'

jest.mock('../../../../../src/utils/logger')

import { mockProducer, mockProducerObserver } from '../../../../helpers/mocks/producer.mock'

const makeIncomingMessage = (
    source: string | null,
    timestamp: number,
    extraWindowedEvents?: Record<string, Record<string, any>[]>
): IncomingRecordingMessage => {
    // @ts-expect-error TODO: Fix underlying types
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

        expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
        const topicMessages = mockProducerObserver.getParsedQueuedMessages()
        expect(topicMessages).toHaveLength(1)
        expect(topicMessages[0].topic).toEqual('clickhouse_ingestion_warnings_test')
        const value = topicMessages[0].messages[0].value!
        const expectedTimestamp = castTimestampOrNow(twoMonthsFromNow, TimestampFormat.ClickHouse)

        expect(value.source).toEqual('plugin-server')
        expect(value.team_id).toEqual(0)
        expect(value.type).toEqual('replay_timestamp_too_far')
        const details = parseJSON(value.details)
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

        expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
        const topicMessages = mockProducerObserver.getParsedQueuedMessages()
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

        expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
        const topicMessages = mockProducerObserver.getParsedQueuedMessages()
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

        expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
        const topicMessages = mockProducerObserver.getParsedQueuedMessages()
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

    describe('switchover date', () => {
        const now = Date.now()
        const switchoverDate = new Date(now)
        const beforeSwitchover = now - 1000 // 1 second before
        const atSwitchover = now
        const afterSwitchover = now + 1000 // 1 second after

        test('processes all events when switchover date is null', async () => {
            const ingester = new ReplayEventsIngester(mockProducer, undefined, null)

            // Create a batch with mixed timestamps and distinct data
            const messages = [
                makeIncomingMessage('web', beforeSwitchover, {
                    main_window: [{ data: { href: 'before1' }, type: 2, timestamp: beforeSwitchover }],
                }),
                makeIncomingMessage('web', atSwitchover, {
                    main_window: [{ data: { href: 'at' }, type: 2, timestamp: atSwitchover }],
                }),
                makeIncomingMessage('web', afterSwitchover, {
                    main_window: [{ data: { href: 'after' }, type: 2, timestamp: afterSwitchover }],
                }),
                makeIncomingMessage('web', beforeSwitchover, {
                    main_window: [{ data: { href: 'before2' }, type: 2, timestamp: beforeSwitchover }],
                }),
            ]

            await ingester.consumeBatch(messages)

            // Should process all messages since switchover is null
            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(4)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages).toHaveLength(4)

            // Verify each message's content
            const processedUrls = topicMessages.map((msg) => msg.messages[0].value?.urls[0] ?? null)
            expect(processedUrls).toEqual(['before1', 'at', 'after', 'before2'])
        })

        test('processes events before switchover date', async () => {
            const ingester = new ReplayEventsIngester(mockProducer, undefined, switchoverDate)
            await ingester.consume(
                makeIncomingMessage('web', beforeSwitchover, {
                    main_window: [{ data: { href: 'before' }, type: 2, timestamp: beforeSwitchover }],
                })
            )

            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages[0].topic).toEqual('clickhouse_session_replay_events_test')
            expect(topicMessages[0].messages[0].value?.urls[0]).toEqual('before')
        })

        test('drops events at or after switchover date', async () => {
            const ingester = new ReplayEventsIngester(mockProducer, undefined, switchoverDate)

            // Test at switchover
            await ingester.consume(
                makeIncomingMessage('web', atSwitchover, {
                    main_window: [{ data: { href: 'at' }, type: 2, timestamp: atSwitchover }],
                })
            )
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()

            // Test after switchover
            await ingester.consume(
                makeIncomingMessage('web', afterSwitchover, {
                    main_window: [{ data: { href: 'after' }, type: 2, timestamp: afterSwitchover }],
                })
            )
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()
        })

        test('processes mixed batch of events correctly', async () => {
            const ingester = new ReplayEventsIngester(mockProducer, undefined, switchoverDate)

            // Create a batch with mixed timestamps and distinct data
            const messages = [
                makeIncomingMessage('web', beforeSwitchover, {
                    main_window: [{ data: { href: 'before1' }, type: 2, timestamp: beforeSwitchover }],
                }),
                makeIncomingMessage('web', atSwitchover, {
                    main_window: [{ data: { href: 'at' }, type: 2, timestamp: atSwitchover }],
                }),
                makeIncomingMessage('web', afterSwitchover, {
                    main_window: [{ data: { href: 'after' }, type: 2, timestamp: afterSwitchover }],
                }),
                makeIncomingMessage('web', beforeSwitchover, {
                    main_window: [{ data: { href: 'before2' }, type: 2, timestamp: beforeSwitchover }],
                }),
            ]

            await ingester.consumeBatch(messages)

            // Should only process the two messages before switchover
            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(2)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages).toHaveLength(2)

            // Verify only the before-switchover messages were processed
            const processedUrls = topicMessages.map((msg) => msg.messages[0].value?.urls[0] ?? null)
            expect(processedUrls).toEqual(['before1', 'before2'])
        })
    })
})
