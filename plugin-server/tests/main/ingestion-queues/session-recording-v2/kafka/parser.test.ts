import { Message } from 'node-rdkafka'
import { promisify } from 'util'
import { gzip } from 'zlib'

import { KafkaMetrics } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/metrics'
import { KafkaParser } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/parser'

const compressWithGzip = promisify(gzip)

describe('KafkaParser', () => {
    let parser: KafkaParser
    let mockKafkaMetrics: jest.Mocked<KafkaMetrics>

    beforeEach(() => {
        mockKafkaMetrics = {
            incrementMessageDropped: jest.fn(),
        } as jest.Mocked<KafkaMetrics>
        parser = new KafkaParser(mockKafkaMetrics)
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

    describe('parseMessage', () => {
        it('successfully parses a valid message', async () => {
            const snapshotItems = [
                { type: 1, timestamp: 1234567890 },
                { type: 2, timestamp: 1234567891 },
            ]
            const message = createMessage({
                data: JSON.stringify({
                    event: '$snapshot_items',
                    properties: {
                        $session_id: 'session1',
                        $window_id: 'window1',
                        $snapshot_items: snapshotItems,
                    },
                }),
                distinct_id: 'user123',
            })

            const result = await parser.parseMessage(message)

            expect(result).toEqual({
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
                    start: 1234567890,
                    end: 1234567891,
                },
                snapshot_source: undefined,
            })
            expect(mockKafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })

        it('successfully parses a gzipped message', async () => {
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
            const message = createMessage(data, { value: gzippedData })

            const result = await parser.parseMessage(message)

            expect(result).toBeTruthy()
            expect(result?.session_id).toBe('session1')
            expect(mockKafkaMetrics.incrementMessageDropped).not.toHaveBeenCalled()
        })
        it('drops message with missing value', async () => {
            const message = createMessage({}, { value: undefined })
            const result = await parser.parseMessage(message)

            expect(result).toBeNull()
            expect(mockKafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('drops message with missing timestamp', async () => {
            const message = createMessage({}, { timestamp: undefined })
            const result = await parser.parseMessage(message)

            expect(result).toBeNull()
            expect(mockKafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'message_value_or_timestamp_is_empty'
            )
        })

        it('drops message with invalid gzip data', async () => {
            const invalidGzip = Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0x00]) // Invalid gzip data
            const message = createMessage({}, { value: invalidGzip })

            const result = await parser.parseMessage(message)

            expect(result).toBeNull()
            expect(mockKafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'invalid_gzip_data'
            )
        })

        it('drops message with invalid JSON', async () => {
            const message = createMessage({}, { value: Buffer.from('invalid json') })
            const result = await parser.parseMessage(message)

            expect(result).toBeNull()
            expect(mockKafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'invalid_json'
            )
        })

        it('drops non-snapshot messages', async () => {
            const message = createMessage({
                data: JSON.stringify({
                    event: 'not_a_snapshot',
                    properties: {
                        $session_id: 'session1',
                    },
                }),
            })

            const result = await parser.parseMessage(message)

            expect(result).toBeNull()
            expect(mockKafkaMetrics.incrementMessageDropped).toHaveBeenCalledWith(
                'session_recordings_blob_ingestion',
                'received_non_snapshot_message'
            )
        })
    })
})
