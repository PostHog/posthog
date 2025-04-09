import { DateTime } from 'luxon'
import { promisify } from 'node:util'
import { Message } from 'node-rdkafka'
import { gzip } from 'zlib'

import { KafkaMessageParser } from './message-parser'
import { KafkaMetrics } from './metrics'

const compressWithGzip = promisify(gzip)

jest.mock('./metrics')

describe('KafkaMessageParser', () => {
    let parser: KafkaMessageParser

    beforeEach(() => {
        jest.clearAllMocks()
        parser = new KafkaMessageParser()
    })

    const createMessage = (data: any, overrides: Partial<Message> = {}): Message => ({
        value: Buffer.from(JSON.stringify(data)),
        size: 100,
        topic: 'test-topic',
        offset: 0,
        partition: 0,
        timestamp: 1234567890,
        ...overrides,
    })

    describe('parseBatch', () => {
        it('handles valid snapshot message including source and lib', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 },
                { type: 2, timestamp: 1234567891 },
            ]
            const messages = [
                createMessage({
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: snapshotItems,
                            $snapshot_source: 'test-source',
                            $lib: 'test-lib',
                        },
                    }),
                    distinct_id: 'user123',
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]).toMatchObject({
                metadata: {
                    partition: 0,
                    topic: 'test-topic',
                    rawSize: 100,
                    offset: 0,
                    timestamp: 1234567890,
                },
                headers: undefined,
                distinct_id: 'user123',
                session_id: 'session1',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                eventsRange: {
                    start: DateTime.fromMillis(1234567890),
                    end: DateTime.fromMillis(1234567891),
                },
                snapshot_source: 'test-source',
                snapshot_library: 'test-lib',
            })
            expect(KafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('handles valid snapshot message missing source and lib', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 },
                { type: 2, timestamp: 1234567891 },
            ]
            const messages = [
                createMessage({
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: snapshotItems,
                        },
                    }),
                    distinct_id: 'user123',
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]).toMatchObject({
                distinct_id: 'user123',
                session_id: 'session1',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                snapshot_source: null,
                snapshot_library: null,
            })
            expect(KafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('handles gzipped message', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 },
                { type: 2, timestamp: 1234567891 },
            ]
            const data = {
                data: JSON.stringify({
                    event: '$snapshot_items',
                    properties: {
                        $session_id: 'session1',
                        $window_id: 'window1',
                        $snapshot_items: snapshotItems,
                    },
                }),
                distinct_id: 'user123',
            }

            const gzippedData = await compressWithGzip(JSON.stringify(data))
            const messages = [createMessage(data, { value: gzippedData })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]).toMatchObject({
                session_id: 'session1',
                distinct_id: 'user123',
                eventsByWindowId: {
                    window1: snapshotItems,
                },
                eventsRange: {
                    start: DateTime.fromMillis(1234567890),
                    end: DateTime.fromMillis(1234567891),
                },
            })
            expect(KafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('filters out message with missing value', async () => {
            const messages = [createMessage({}, { value: null })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('filters out message with missing timestamp', async () => {
            const messages = [createMessage({}, { timestamp: undefined })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('filters out message with invalid gzip data', async () => {
            const messages = [createMessage({}, { value: Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0x00]) })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'invalid_gzip_data'
            )
        })

        it('filters out message with invalid json', async () => {
            const messages = [createMessage({}, { value: Buffer.from('invalid json') })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'invalid_json'
            )
        })

        it('filters out message with missing distinct_id', async () => {
            const messages = [
                createMessage({
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: [{ timestamp: 1, type: 2 }],
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'invalid_message_payload'
            )
        })

        it('filters out non-snapshot message', async () => {
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: 'not_a_snapshot',
                        properties: {
                            $session_id: 'session1',
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'received_non_snapshot_message'
            )
        })

        it('handles empty batch', async () => {
            const results = await parser.parseBatch([])
            expect(results).toEqual([])
        })

        it('processes multiple messages in parallel', async () => {
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: [{ timestamp: 1, type: 2 }],
                        },
                    }),
                }),
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session2',
                            $window_id: 'window2',
                            $snapshot_items: [{ timestamp: 2, type: 2 }],
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(2)
            expect(results[0]?.session_id).toBe('session1')
            expect(results[1]?.session_id).toBe('session2')
        })

        it('filters out events with zero or negative timestamps', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 },
                { type: 2, timestamp: 0 },
                { type: 3, timestamp: -1000 },
                { type: 4, timestamp: 1234567891 },
            ]
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: snapshotItems,
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]?.eventsByWindowId['window1']).toHaveLength(2)
            expect(results[0]?.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1234567890 },
                { type: 4, timestamp: 1234567891 },
            ])
            expect(results[0]?.eventsRange).toEqual({
                start: DateTime.fromMillis(1234567890),
                end: DateTime.fromMillis(1234567891),
            })
        })

        it('uses min/max for timestamp range instead of first/last', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 }, // Not the smallest
                { type: 2, timestamp: 1234567889 }, // Smallest
                { type: 3, timestamp: 1234567892 }, // Not the largest
                { type: 4, timestamp: 1234567893 }, // Largest
                { type: 5, timestamp: 1234567891 }, // Middle
            ]
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session1',
                            $window_id: 'window1',
                            $snapshot_items: snapshotItems,
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]?.eventsRange).toEqual({
                start: DateTime.fromMillis(1234567889), // Should be smallest timestamp
                end: DateTime.fromMillis(1234567893), // Should be largest timestamp
            })
        })
    })
})
