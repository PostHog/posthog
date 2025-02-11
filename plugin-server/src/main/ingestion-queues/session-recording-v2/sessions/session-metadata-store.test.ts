import { DateTime } from 'luxon'

import { KafkaProducerWrapper, TopicMessage } from '../../../../kafka/producer'
import { SessionMetadataStore } from './session-metadata-store'

describe('SessionMetadataStore', () => {
    let store: SessionMetadataStore
    let mockProducer: jest.Mocked<KafkaProducerWrapper>

    beforeEach(() => {
        mockProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        store = new SessionMetadataStore(mockProducer)
    })

    it('should queue events to kafka with correct data', async () => {
        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                blockLength: 100,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: 's3://bucket/file1?range=bytes=0-99',
            },
            {
                sessionId: 'different456',
                teamId: 2,
                distinctId: 'user2',
                blockLength: 150,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:01.500Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:03.500Z'),
                blockUrl: 's3://bucket/file1?range=bytes=100-249',
            },
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                blockLength: 200,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:03.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:05.000Z'),
                blockUrl: 's3://bucket/file1?range=bytes=250-449',
            },
        ]

        await store.storeSessionBlocks(blocks)

        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        expect(queuedMessage.topic).toBe('clickhouse_session_replay_events_v2_test_test')
        const queuedMessages = queuedMessage.messages
        const parsedEvents = queuedMessages.map((msg) => JSON.parse(msg.value as string))

        expect(parsedEvents).toMatchObject([
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                distinct_id: 'user1',
                first_timestamp: '2025-01-01 10:00:00.000',
                last_timestamp: '2025-01-01 10:00:02.000',
                block_url: 's3://bucket/file1?range=bytes=0-99',
            },
            {
                uuid: expect.any(String),
                session_id: 'different456',
                team_id: 2,
                distinct_id: 'user2',
                first_timestamp: '2025-01-01 10:00:01.500',
                last_timestamp: '2025-01-01 10:00:03.500',
                block_url: 's3://bucket/file1?range=bytes=100-249',
            },
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                distinct_id: 'user1',
                first_timestamp: '2025-01-01 10:00:03.000',
                last_timestamp: '2025-01-01 10:00:05.000',
                block_url: 's3://bucket/file1?range=bytes=250-449',
            },
        ])

        // Verify UUIDs are unique
        const uuids = parsedEvents.map((event) => event.uuid)
        expect(new Set(uuids).size).toBe(3)

        // Verify keys are set to correct session IDs
        expect(queuedMessages[0].key).toEqual('session123')
        expect(queuedMessages[1].key).toEqual('different456')
        expect(queuedMessages[2].key).toEqual('session123')
    })

    it('should handle empty blocks array', async () => {
        await store.storeSessionBlocks([])
        expect(mockProducer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_session_replay_events_v2_test_test',
            messages: [],
        })
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.queueMessages.mockRejectedValueOnce(error)

        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                distinctId: 'user1',
                blockLength: 100,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: null,
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
                blockLength: 100,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                blockUrl: null,
            },
        ]

        await store.storeSessionBlocks(blocks)

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        const parsedEvent = JSON.parse(queuedMessage.messages[0].value as string)
        expect(parsedEvent.block_url).toBeNull()
        expect(parsedEvent.distinct_id).toBe('user1')
    })
})
