import { DateTime } from 'luxon'

import { KafkaProducerWrapper, TopicMessage } from '../../../../kafka/producer'
import { parseJSON } from '../../../../utils/json-parse'
import { SessionMetadataStore } from './session-metadata-store'

describe('SessionMetadataStore', () => {
    let store: SessionMetadataStore
    let mockProducer: jest.Mocked<KafkaProducerWrapper>

    beforeEach(() => {
        mockProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        store = new SessionMetadataStore(mockProducer, 'clickhouse_session_replay_events')
    })

    it('should queue events to kafka with correct data', async () => {
        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch123',
                blockLength: 100,
                eventCount: 25,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: 's3://bucket/file1?range=bytes=0-99',
                firstUrl: 'https://example.com',
                urls: ['https://example.com', 'https://example.com/page2'],
                clickCount: 5,
                keypressCount: 10,
                mouseActivityCount: 15,
                activeMilliseconds: 2000,
                consoleLogCount: 3,
                consoleWarnCount: 2,
                consoleErrorCount: 1,
                size: 1024,
                messageCount: 50,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
            {
                sessionId: 'different456',
                teamId: 2,
                distinctId: 'user2',
                batchId: 'batch123',
                blockLength: 150,
                eventCount: 15,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:01.500Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:03.500Z'),
                blockUrl: 's3://bucket/file1?range=bytes=100-249',
                firstUrl: 'https://example.com/different',
                urls: ['https://example.com/different'],
                clickCount: 2,
                keypressCount: 5,
                mouseActivityCount: 8,
                activeMilliseconds: 1500,
                consoleLogCount: 1,
                consoleWarnCount: 1,
                consoleErrorCount: 0,
                size: 512,
                messageCount: 30,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch123',
                blockLength: 200,
                eventCount: 35,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:03.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:05.000Z'),
                blockUrl: 's3://bucket/file1?range=bytes=250-449',
                firstUrl: 'https://example.com',
                urls: ['https://example.com', 'https://example.com/page3'],
                clickCount: 7,
                keypressCount: 15,
                mouseActivityCount: 20,
                activeMilliseconds: 2500,
                consoleLogCount: 4,
                consoleWarnCount: 1,
                consoleErrorCount: 2,
                size: 2048,
                messageCount: 70,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await store.storeSessionBlocks(blocks)

        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        expect(queuedMessage.topic).toBe('clickhouse_session_replay_events')
        const queuedMessages = queuedMessage.messages
        const parsedEvents = queuedMessages.map((msg) => parseJSON(msg.value as string))

        expect(parsedEvents).toMatchObject([
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                distinct_id: 'user1',
                batch_id: 'batch123',
                first_timestamp: '2025-01-01 10:00:00.000',
                last_timestamp: '2025-01-01 10:00:02.000',
                block_url: 's3://bucket/file1?range=bytes=0-99',
                first_url: 'https://example.com',
                urls: ['https://example.com', 'https://example.com/page2'],
                click_count: 5,
                keypress_count: 10,
                mouse_activity_count: 15,
                active_milliseconds: 2000,
                console_log_count: 3,
                console_warn_count: 2,
                console_error_count: 1,
                size: 1024,
                message_count: 50,
                snapshot_source: 'web',
                snapshot_library: 'rrweb@1.0.0',
                event_count: 25,
                retention_period_days: 30,
            },
            {
                uuid: expect.any(String),
                session_id: 'different456',
                team_id: 2,
                distinct_id: 'user2',
                batch_id: 'batch123',
                first_timestamp: '2025-01-01 10:00:01.500',
                last_timestamp: '2025-01-01 10:00:03.500',
                block_url: 's3://bucket/file1?range=bytes=100-249',
                first_url: 'https://example.com/different',
                urls: ['https://example.com/different'],
                click_count: 2,
                keypress_count: 5,
                mouse_activity_count: 8,
                active_milliseconds: 1500,
                console_log_count: 1,
                console_warn_count: 1,
                console_error_count: 0,
                size: 512,
                message_count: 30,
                snapshot_source: 'web',
                snapshot_library: 'rrweb@1.0.0',
                event_count: 15,
                retention_period_days: 30,
            },
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                distinct_id: 'user1',
                batch_id: 'batch123',
                first_timestamp: '2025-01-01 10:00:03.000',
                last_timestamp: '2025-01-01 10:00:05.000',
                block_url: 's3://bucket/file1?range=bytes=250-449',
                first_url: 'https://example.com',
                urls: ['https://example.com', 'https://example.com/page3'],
                click_count: 7,
                keypress_count: 15,
                mouse_activity_count: 20,
                active_milliseconds: 2500,
                console_log_count: 4,
                console_warn_count: 1,
                console_error_count: 2,
                size: 2048,
                message_count: 70,
                snapshot_source: 'web',
                snapshot_library: 'rrweb@1.0.0',
                event_count: 35,
                retention_period_days: 30,
            },
        ])

        // Verify UUIDs are unique
        const uuids = parsedEvents.map((event) => event.uuid)
        expect(new Set(uuids).size).toBe(3)

        // Verify keys are set to correct session IDs
        expect(queuedMessages[0].key).toEqual('session123')
        expect(queuedMessages[1].key).toEqual('different456')
        expect(queuedMessages[2].key).toEqual('session123')

        expect(mockProducer.flush).toHaveBeenCalledTimes(1)
    })

    it('should handle empty blocks array', async () => {
        await store.storeSessionBlocks([])
        expect(mockProducer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_session_replay_events',
            messages: [],
        })
        expect(mockProducer.flush).toHaveBeenCalledTimes(1)
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.queueMessages.mockRejectedValueOnce(error)

        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch123',
                blockLength: 100,
                eventCount: 10,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: null,
                firstUrl: 'https://example.com',
                urls: ['https://example.com'],
                clickCount: 3,
                keypressCount: 7,
                mouseActivityCount: 12,
                activeMilliseconds: 1000,
                consoleLogCount: 1,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                size: 512,
                messageCount: 25,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await expect(store.storeSessionBlocks(blocks)).rejects.toThrow(error)
    })

    it('should handle null block urls', async () => {
        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch123',
                blockLength: 100,
                eventCount: 8,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: null,
                firstUrl: 'https://example.com',
                urls: ['https://example.com'],
                clickCount: 3,
                keypressCount: 7,
                mouseActivityCount: 12,
                activeMilliseconds: 1000,
                consoleLogCount: 1,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                size: 512,
                messageCount: 25,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await store.storeSessionBlocks(blocks)

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        const parsedEvent = parseJSON(queuedMessage.messages[0].value as string)
        expect(parsedEvent.event_count).toBe(8)
        expect(parsedEvent.block_url).toBeNull()
        expect(parsedEvent.distinct_id).toBe('user1')
        expect(parsedEvent.first_url).toBe('https://example.com')
        expect(parsedEvent.urls).toEqual(['https://example.com'])
        expect(parsedEvent.click_count).toBe(3)
        expect(parsedEvent.keypress_count).toBe(7)
        expect(parsedEvent.mouse_activity_count).toBe(12)
        expect(parsedEvent.active_milliseconds).toBe(1000)
        expect(parsedEvent.console_log_count).toBe(1)
        expect(parsedEvent.console_warn_count).toBe(0)
        expect(parsedEvent.console_error_count).toBe(0)
        expect(parsedEvent.size).toBe(512)
        expect(parsedEvent.message_count).toBe(25)
        expect(parsedEvent.snapshot_source).toBe('web')
        expect(parsedEvent.snapshot_library).toBe('rrweb@1.0.0')
        expect(mockProducer.flush).toHaveBeenCalledTimes(1)
    })

    it('should preserve batch IDs when storing blocks', async () => {
        const blocks = [
            {
                sessionId: 'session1',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch1',
                blockLength: 100,
                eventCount: 12,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: 's3://bucket/file1',
                firstUrl: 'https://example.com',
                urls: ['https://example.com'],
                clickCount: 1,
                keypressCount: 2,
                mouseActivityCount: 3,
                activeMilliseconds: 500,
                consoleLogCount: 1,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                size: 256,
                messageCount: 15,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
            {
                sessionId: 'session2',
                teamId: 1,
                distinctId: 'user2',
                batchId: 'batch2',
                blockLength: 200,
                eventCount: 18,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:03.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:05.000Z'),
                blockUrl: 's3://bucket/file2',
                firstUrl: 'https://example.com/other',
                urls: ['https://example.com/other'],
                clickCount: 4,
                keypressCount: 5,
                mouseActivityCount: 6,
                activeMilliseconds: 750,
                consoleLogCount: 2,
                consoleWarnCount: 1,
                consoleErrorCount: 1,
                size: 384,
                messageCount: 20,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await store.storeSessionBlocks(blocks)

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        const parsedEvents = queuedMessage.messages.map((msg) => parseJSON(msg.value as string))

        expect(parsedEvents[0].batch_id).toBe('batch1')
        expect(parsedEvents[1].batch_id).toBe('batch2')
        expect(parsedEvents[0]).toMatchObject({
            first_url: 'https://example.com',
            urls: ['https://example.com'],
            event_count: 12,
            click_count: 1,
            keypress_count: 2,
            mouse_activity_count: 3,
            active_milliseconds: 500,
            console_log_count: 1,
            console_warn_count: 0,
            console_error_count: 0,
            size: 256,
            message_count: 15,
            snapshot_source: 'web',
            snapshot_library: 'rrweb@1.0.0',
            retention_period_days: 30,
        })
        expect(parsedEvents[1]).toMatchObject({
            first_url: 'https://example.com/other',
            urls: ['https://example.com/other'],
            event_count: 18,
            click_count: 4,
            keypress_count: 5,
            mouse_activity_count: 6,
            active_milliseconds: 750,
            console_log_count: 2,
            console_warn_count: 1,
            console_error_count: 1,
            size: 384,
            message_count: 20,
            snapshot_source: 'web',
            snapshot_library: 'rrweb@1.0.0',
            retention_period_days: 30,
        })
        expect(mockProducer.flush).toHaveBeenCalledTimes(1)
    })

    it('should handle flush errors', async () => {
        const error = new Error('Kafka flush error')
        mockProducer.flush.mockRejectedValueOnce(error)

        const blocks = [
            {
                sessionId: 'session1',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch1',
                blockLength: 100,
                eventCount: 15,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: 's3://bucket/file1',
                firstUrl: 'https://example.com',
                urls: ['https://example.com'],
                clickCount: 3,
                keypressCount: 7,
                mouseActivityCount: 12,
                activeMilliseconds: 1000,
                consoleLogCount: 1,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                size: 512,
                messageCount: 25,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await expect(store.storeSessionBlocks(blocks)).rejects.toThrow(error)
        expect(mockProducer.queueMessages).toHaveBeenCalled()
        expect(mockProducer.flush).toHaveBeenCalledTimes(1)
    })

    it('should use the provided kafka topic name', async () => {
        const customTopic = 'custom_topic_name'
        const customStore = new SessionMetadataStore(mockProducer, customTopic)

        const blocks = [
            {
                sessionId: 'session1',
                teamId: 1,
                distinctId: 'user1',
                batchId: 'batch1',
                blockLength: 100,
                eventCount: 15,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: 's3://bucket/file1',
                firstUrl: 'https://example.com',
                urls: ['https://example.com'],
                clickCount: 3,
                keypressCount: 7,
                mouseActivityCount: 12,
                activeMilliseconds: 1000,
                consoleLogCount: 1,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                size: 512,
                messageCount: 25,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                retentionPeriodDays: 30,
            },
        ]

        await customStore.storeSessionBlocks(blocks)

        expect(mockProducer.queueMessages).toHaveBeenCalledWith(
            expect.objectContaining({
                topic: customTopic,
            })
        )
    })
})
