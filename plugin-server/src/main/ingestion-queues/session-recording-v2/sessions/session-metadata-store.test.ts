import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { SessionMetadataStore } from './session-metadata-store'

describe('SessionMetadataStore', () => {
    let store: SessionMetadataStore
    let mockProducer: jest.Mocked<KafkaProducerWrapper>

    beforeEach(() => {
        mockProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        store = new SessionMetadataStore(mockProducer)
    })

    it('should produce events to kafka with correct data', async () => {
        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                blockLength: 100,
                startTimestamp: 1000,
                endTimestamp: 2000,
                blockUrl: 's3://bucket/file1?range=bytes=0-99',
            },
            {
                sessionId: 'different456',
                teamId: 2,
                blockLength: 150,
                startTimestamp: 1500,
                endTimestamp: 2500,
                blockUrl: 's3://bucket/file1?range=bytes=100-249',
            },
            {
                sessionId: 'session123',
                teamId: 1,
                blockLength: 200,
                startTimestamp: 2000,
                endTimestamp: 3000,
                blockUrl: 's3://bucket/file1?range=bytes=250-449',
            },
        ]

        await store.storeSessionBlocks(blocks)

        expect(mockProducer.produce).toHaveBeenCalledTimes(3)
        const producedEvents = mockProducer.produce.mock.calls.map((call) => JSON.parse(call[0].value!.toString()))

        expect(producedEvents).toMatchObject([
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                start_timestamp: 1000,
                end_timestamp: 2000,
                block_url: 's3://bucket/file1?range=bytes=0-99',
            },
            {
                uuid: expect.any(String),
                session_id: 'different456',
                team_id: 2,
                start_timestamp: 1500,
                end_timestamp: 2500,
                block_url: 's3://bucket/file1?range=bytes=100-249',
            },
            {
                uuid: expect.any(String),
                session_id: 'session123',
                team_id: 1,
                start_timestamp: 2000,
                end_timestamp: 3000,
                block_url: 's3://bucket/file1?range=bytes=250-449',
            },
        ])

        // Verify UUIDs are unique
        const uuids = producedEvents.map((event) => event.uuid)
        expect(new Set(uuids).size).toBe(3)

        // Verify keys are set to correct session IDs
        expect(mockProducer.produce.mock.calls[0][0].key).toEqual(Buffer.from('session123'))
        expect(mockProducer.produce.mock.calls[1][0].key).toEqual(Buffer.from('different456'))
        expect(mockProducer.produce.mock.calls[2][0].key).toEqual(Buffer.from('session123'))
    })

    it('should handle empty blocks array', async () => {
        await store.storeSessionBlocks([])
        expect(mockProducer.produce).not.toHaveBeenCalled()
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.produce.mockRejectedValueOnce(error)

        const blocks = [
            {
                sessionId: 'session123',
                teamId: 1,
                blockLength: 100,
                startTimestamp: 1000,
                endTimestamp: 2000,
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
                blockLength: 100,
                startTimestamp: 1000,
                endTimestamp: 2000,
                blockUrl: null,
            },
        ]

        await store.storeSessionBlocks(blocks)

        const producedEvent = JSON.parse(mockProducer.produce.mock.calls[0][0].value!.toString())
        expect(producedEvent.block_url).toBeNull()
    })
})
