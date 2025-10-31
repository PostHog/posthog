import { DateTime } from 'luxon'
import { promisify } from 'node:util'
import { gzip } from 'zlib'

import { dlq, isDlqResult, isOkResult } from '../../../../ingestion/pipelines/results'
import { createTestMessage } from '../test-helpers'
import { createParseKafkaMessageStep } from './parse-kafka-message'

const compressWithGzip = promisify(gzip)

describe('parse-kafka-message', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2023-01-01T00:00:00.000Z'))
    })

    it('handles valid snapshot message including source and lib', async () => {
        const step = createParseKafkaMessageStep()
        const snapshotItems = [
            { type: 1, timestamp: 1672527600000 },
            { type: 2, timestamp: 1672527601000 },
        ]
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: snapshotItems,
                $snapshot_source: 'test-source',
                $lib: 'test-lib',
            },
        }
        const rawMessage = {
            distinct_id: 'user123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.message).toEqual(message)
            expect(result.value.headers).toEqual(headers)
            expect(result.value.parsedMessage).toMatchObject({
                metadata: {
                    partition: 0,
                    topic: 'test-topic',
                    rawSize: 1024,
                    offset: 0,
                    timestamp: 1672527600000,
                },
                distinct_id: 'user123',
                session_id: 'session1',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                eventsRange: {
                    start: DateTime.fromMillis(1672527600000),
                    end: DateTime.fromMillis(1672527601000),
                },
                snapshot_source: 'test-source',
                snapshot_library: 'test-lib',
            })
        }
    })

    it('handles valid snapshot message missing source and lib', async () => {
        const step = createParseKafkaMessageStep()
        const snapshotItems = [
            { type: 1, timestamp: 1672527600000 },
            { type: 2, timestamp: 1672527601000 },
        ]
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: snapshotItems,
            },
        }
        const rawMessage = {
            distinct_id: 'user123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.parsedMessage).toMatchObject({
                distinct_id: 'user123',
                session_id: 'session1',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                snapshot_source: null,
                snapshot_library: null,
            })
        }
    })

    it('handles gzipped message', async () => {
        const step = createParseKafkaMessageStep()
        const snapshotItems = [
            { type: 1, timestamp: 1672527600000 },
            { type: 2, timestamp: 1672527601000 },
        ]
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: snapshotItems,
            },
        }
        const rawMessage = {
            data: JSON.stringify(event),
            distinct_id: 'user123',
        }

        const gzippedData = await compressWithGzip(JSON.stringify(rawMessage))
        const message = createTestMessage({ value: gzippedData, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.parsedMessage).toMatchObject({
                session_id: 'session1',
                distinct_id: 'user123',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                eventsRange: {
                    start: DateTime.fromMillis(1672527600000),
                    end: DateTime.fromMillis(1672527601000),
                },
            })
        }
    })

    it('should return dlq when message value is empty', async () => {
        const step = createParseKafkaMessageStep()
        const message = createTestMessage({ value: null })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('message_value_or_timestamp_is_empty'))
    })

    it('should return dlq when message timestamp is missing', async () => {
        const step = createParseKafkaMessageStep()
        const message = createTestMessage({ value: Buffer.from('test'), timestamp: undefined })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('message_value_or_timestamp_is_empty'))
    })

    it('should return dlq when gzip data is invalid', async () => {
        const step = createParseKafkaMessageStep()
        const message = createTestMessage({
            value: Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0x00]),
            timestamp: 1672527600000,
        })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('invalid_gzip_data'))
    })

    it('should return dlq when JSON is invalid', async () => {
        const step = createParseKafkaMessageStep()
        const message = createTestMessage({ value: Buffer.from('invalid json'), timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('invalid_json'))
    })

    it('should return dlq when distinct_id is missing', async () => {
        const step = createParseKafkaMessageStep()
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: [{ timestamp: 1, type: 2 }],
            },
        }
        const rawMessage = {
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('invalid_message_payload'))
    })

    it('should return dlq when event is not a snapshot event', async () => {
        const step = createParseKafkaMessageStep()
        const event = {
            event: 'not_a_snapshot',
            properties: {
                $session_id: 'session1',
            },
        }
        const rawMessage = {
            distinct_id: 'user123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('received_non_snapshot_message'))
    })

    it('should return dlq when snapshot items are missing', async () => {
        const step = createParseKafkaMessageStep()
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session-123',
            },
        }
        const rawMessage = {
            distinct_id: 'user-123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('received_non_snapshot_message'))
    })

    it('should return dlq when snapshot items contain no valid events', async () => {
        const step = createParseKafkaMessageStep()
        const event = {
            event: '$snapshot_items',
            properties: {
                $snapshot_items: [{ timestamp: -1 }],
                $session_id: 'session-123',
            },
        }
        const rawMessage = {
            distinct_id: 'user-123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('message_contained_no_valid_rrweb_events'))
    })

    it('filters out events with zero or negative timestamps', async () => {
        const step = createParseKafkaMessageStep()
        const snapshotItems = [
            { type: 1, timestamp: 1672527600000 },
            { type: 2, timestamp: 0 },
            { type: 3, timestamp: -1000 },
            { type: 4, timestamp: 1672527601000 },
        ]
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: snapshotItems,
            },
        }
        const rawMessage = {
            distinct_id: 'user123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.parsedMessage.eventsByWindowId['window1']).toHaveLength(2)
            expect(result.value.parsedMessage.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1672527600000 },
                { type: 4, timestamp: 1672527601000 },
            ])
            expect(result.value.parsedMessage.eventsRange).toEqual({
                start: DateTime.fromMillis(1672527600000),
                end: DateTime.fromMillis(1672527601000),
            })
        }
    })

    it('uses min/max for timestamp range instead of first/last', async () => {
        const step = createParseKafkaMessageStep()
        const snapshotItems = [
            { type: 1, timestamp: 1672527600000 }, // Not the smallest
            { type: 2, timestamp: 1672527599000 }, // Smallest
            { type: 3, timestamp: 1672527602000 }, // Not the largest
            { type: 4, timestamp: 1672527603000 }, // Largest
            { type: 5, timestamp: 1672527601000 }, // Middle
        ]
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: snapshotItems,
            },
        }
        const rawMessage = {
            distinct_id: 'user123',
            data: JSON.stringify(event),
        }
        const value = Buffer.from(JSON.stringify(rawMessage))
        const message = createTestMessage({ value, timestamp: 1672527600000 })
        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.parsedMessage.eventsRange).toEqual({
                start: DateTime.fromMillis(1672527599000), // Should be smallest timestamp
                end: DateTime.fromMillis(1672527603000), // Should be largest timestamp
            })
        }
    })

    it('filters out snapshots with events too far in the future', async () => {
        const step = createParseKafkaMessageStep()
        const event1 = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: [
                    { type: 1, timestamp: 1672959600000 }, // 6 days in the future, valid timestamp
                    { type: 2, timestamp: 1672527603000 }, // 3 seconds in the future, valid timestamp
                    { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                ],
            },
        }
        const rawMessage1 = {
            distinct_id: 'user123',
            data: JSON.stringify(event1),
        }
        const message1 = createTestMessage({
            value: Buffer.from(JSON.stringify(rawMessage1)),
            timestamp: 1672527600000,
        })

        const event2 = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session2',
                $window_id: 'window2',
                $snapshot_items: [
                    { type: 1, timestamp: 1672959600000 }, // 6 days in the future, valid timestamp
                    { type: 2, timestamp: 1673218800000 }, // 8 days in the future, invalid timestamp
                    { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                ],
            },
        }
        const rawMessage2 = {
            distinct_id: 'user123',
            data: JSON.stringify(event2),
        }
        const message2 = createTestMessage({
            value: Buffer.from(JSON.stringify(rawMessage2)),
            timestamp: 1672527600000,
        })

        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result1 = await step({ message: message1, headers })
        const result2 = await step({ message: message2, headers })

        expect(isOkResult(result1)).toBe(true)
        if (isOkResult(result1)) {
            expect(result1.value.parsedMessage.eventsByWindowId['window1']).toHaveLength(3)
            expect(result1.value.parsedMessage.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1672959600000 },
                { type: 2, timestamp: 1672527603000 },
                { type: 3, timestamp: 1672527600000 },
            ])
            expect(result1.value.parsedMessage.eventsRange).toEqual({
                start: DateTime.fromMillis(1672527600000),
                end: DateTime.fromMillis(1672959600000),
            })
        }

        expect(isDlqResult(result2)).toBe(true)
        expect(result2).toEqual(dlq('message_timestamp_diff_too_large'))
    })

    it('filters out snapshots with events too far in the past', async () => {
        const step = createParseKafkaMessageStep()
        const event1 = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session1',
                $window_id: 'window1',
                $snapshot_items: [
                    { type: 1, timestamp: 1672095600000 }, // 6 days in the past, valid timestamp
                    { type: 2, timestamp: 1672527595000 }, // 5 seconds in the past, valid timestamp
                    { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                ],
            },
        }
        const rawMessage1 = {
            distinct_id: 'user123',
            data: JSON.stringify(event1),
        }
        const message1 = createTestMessage({
            value: Buffer.from(JSON.stringify(rawMessage1)),
            timestamp: 1672527600000,
        })

        const event2 = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session2',
                $window_id: 'window2',
                $snapshot_items: [
                    { type: 1, timestamp: 1672095600000 }, // 6 days in the past, valid timestamp
                    { type: 2, timestamp: 1671836400000 }, // 8 days in the past, invalid timestamp
                    { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                ],
            },
        }
        const rawMessage2 = {
            distinct_id: 'user123',
            data: JSON.stringify(event2),
        }
        const message2 = createTestMessage({
            value: Buffer.from(JSON.stringify(rawMessage2)),
            timestamp: 1672527600000,
        })

        const headers = { token: 'test-token', distinct_id: 'user123', force_disable_person_processing: false }

        const result1 = await step({ message: message1, headers })
        const result2 = await step({ message: message2, headers })

        expect(isOkResult(result1)).toBe(true)
        if (isOkResult(result1)) {
            expect(result1.value.parsedMessage.eventsByWindowId['window1']).toHaveLength(3)
            expect(result1.value.parsedMessage.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1672095600000 },
                { type: 2, timestamp: 1672527595000 },
                { type: 3, timestamp: 1672527600000 },
            ])
            expect(result1.value.parsedMessage.eventsRange).toEqual({
                start: DateTime.fromMillis(1672095600000),
                end: DateTime.fromMillis(1672527600000),
            })
        }

        expect(isDlqResult(result2)).toBe(true)
        expect(result2).toEqual(dlq('message_timestamp_diff_too_large'))
    })
})
