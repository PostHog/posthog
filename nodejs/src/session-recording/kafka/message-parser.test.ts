import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { gzip } from 'zlib'

import { KafkaMessageParser } from './message-parser'
import { KafkaMetrics } from './metrics'

const compressWithGzip = promisify(gzip)

jest.mock('./metrics')

describe('KafkaMessageParser', () => {
    let parser: KafkaMessageParser

    afterEach(() => {
        jest.useRealTimers()
    })

    beforeEach(() => {
        jest.clearAllMocks()
        parser = new KafkaMessageParser()

        jest.useFakeTimers()
        jest.setSystemTime(new Date('2023-01-01T00:00:00.000Z'))
    })

    const createMessage = (data: any, overrides: Partial<Message> = {}): Message => ({
        value: Buffer.from(JSON.stringify(data)),
        size: 100,
        topic: 'test-topic',
        offset: 0,
        partition: 0,
        timestamp: 1672527600000,
        ...overrides,
    })

    describe('parseBatch', () => {
        it('handles valid snapshot message including source and lib', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1672527600000 },
                { type: 2, timestamp: 1672527601000 },
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
                    timestamp: 1672527600000,
                },
                headers: undefined,
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
            expect(KafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('handles valid snapshot message missing source and lib', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1672527600000 },
                { type: 2, timestamp: 1672527601000 },
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
                { type: 1, timestamp: 1672527600000 },
                { type: 2, timestamp: 1672527601000 },
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
                    start: DateTime.fromMillis(1672527600000),
                    end: DateTime.fromMillis(1672527601000),
                },
            })
            expect(KafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('filters out message with missing value', async () => {
            const messages = [createMessage({}, { value: null })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion_v2',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('filters out message with missing timestamp', async () => {
            const messages = [createMessage({}, { timestamp: undefined })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion_v2',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('filters out message with invalid gzip data', async () => {
            const messages = [createMessage({}, { value: Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0x00]) })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion_v2',
                'invalid_gzip_data'
            )
        })

        it('filters out message with invalid json', async () => {
            const messages = [createMessage({}, { value: Buffer.from('invalid json') })]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(0)
            expect(KafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion_v2',
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
                'session_recordings_blob_ingestion_v2',
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
                'session_recordings_blob_ingestion_v2',
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
                            $snapshot_items: [{ timestamp: 1672527601000, type: 2 }],
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
                            $snapshot_items: [{ timestamp: 1672527601000, type: 2 }],
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
                { type: 1, timestamp: 1672527600000 },
                { type: 2, timestamp: 0 },
                { type: 3, timestamp: -1000 },
                { type: 4, timestamp: 1672527601000 },
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
                { type: 1, timestamp: 1672527600000 },
                { type: 4, timestamp: 1672527601000 },
            ])
            expect(results[0]?.eventsRange).toEqual({
                start: DateTime.fromMillis(1672527600000),
                end: DateTime.fromMillis(1672527601000),
            })
        })

        it('uses min/max for timestamp range instead of first/last', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1672527600000 }, // Not the smallest
                { type: 2, timestamp: 1672527599000 }, // Smallest
                { type: 3, timestamp: 1672527602000 }, // Not the largest
                { type: 4, timestamp: 1672527603000 }, // Largest
                { type: 5, timestamp: 1672527601000 }, // Middle
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
                start: DateTime.fromMillis(1672527599000), // Should be smallest timestamp
                end: DateTime.fromMillis(1672527603000), // Should be largest timestamp
            })
        })

        it('filters out snapshots with events in the future', async () => {
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
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
                    }),
                }),
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
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
                    }),
                }),

                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session3',
                            $window_id: 'window3',
                            $snapshot_items: [
                                { type: 1, timestamp: 1672959600000 }, // 6 days in the future, valid timestamp
                                { type: 2, timestamp: 1704063600000 }, // 365 days in the future, invalid timestamp
                                { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                            ],
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]?.eventsByWindowId['window1']).toHaveLength(3)
            expect(results[0]?.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1672959600000 },
                { type: 2, timestamp: 1672527603000 },
                { type: 3, timestamp: 1672527600000 },
            ])
            expect(results[0]?.eventsRange).toEqual({
                start: DateTime.fromMillis(1672527600000),
                end: DateTime.fromMillis(1672959600000),
            })
        })

        it('filters out snapshots with events in the past', async () => {
            const messages = [
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
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
                    }),
                }),
                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
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
                    }),
                }),

                createMessage({
                    distinct_id: 'user123',
                    data: JSON.stringify({
                        event: '$snapshot_items',
                        properties: {
                            $session_id: 'session3',
                            $window_id: 'window3',
                            $snapshot_items: [
                                { type: 1, timestamp: 1672095600000 }, // 6 days in the past, valid timestamp
                                { type: 2, timestamp: 1640991600000 }, // 365 days in the past, invalid timestamp
                                { type: 3, timestamp: 1672527600000 }, // now, valid timestamp
                            ],
                        },
                    }),
                }),
            ]

            const results = await parser.parseBatch(messages)

            expect(results).toHaveLength(1)
            expect(results[0]?.eventsByWindowId['window1']).toHaveLength(3)
            expect(results[0]?.eventsByWindowId['window1']).toEqual([
                { type: 1, timestamp: 1672095600000 },
                { type: 2, timestamp: 1672527595000 },
                { type: 3, timestamp: 1672527600000 },
            ])
            expect(results[0]?.eventsRange).toEqual({
                start: DateTime.fromMillis(1672095600000),
                end: DateTime.fromMillis(1672527600000),
            })
        })
    })
})
