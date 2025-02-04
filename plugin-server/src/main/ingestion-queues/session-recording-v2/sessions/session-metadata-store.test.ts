import { validate as validateUuid, version as uuidVersion } from 'uuid'

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

    it('should produce event to kafka with correct data', async () => {
        const metadata = {
            sessionId: 'session123',
            teamId: 1,
            startTimestamp: 1000,
            endTimestamp: 2000,
            blockStartOffset: 0,
            blockLength: 100,
        }

        await store.storeSessionBlock(metadata)

        expect(mockProducer.produce).toHaveBeenCalledTimes(1)
        expect(mockProducer.produce).toHaveBeenCalledWith({
            topic: 'session_replay_events_v2',
            key: Buffer.from('session123'),
            value: expect.any(Buffer),
        })

        // Parse the produced value to verify its contents
        const producedValue = JSON.parse(mockProducer.produce.mock.calls[0][0].value!.toString())
        expect(producedValue).toEqual({
            uuid: expect.any(String),
            session_id: 'session123',
            team_id: 1,
            start_timestamp: 1000,
            end_timestamp: 2000,
            urls: expect.any(Array),
        })
    })

    it('should generate unique UUIDs for each event', async () => {
        const metadata = {
            sessionId: 'session123',
            teamId: 1,
            startTimestamp: 1000,
            endTimestamp: 2000,
            blockStartOffset: 0,
            blockLength: 100,
        }

        await store.storeSessionBlock(metadata)
        await store.storeSessionBlock(metadata)

        const firstUuid = JSON.parse(mockProducer.produce.mock.calls[0][0].value!.toString()).uuid
        const secondUuid = JSON.parse(mockProducer.produce.mock.calls[1][0].value!.toString()).uuid

        expect(firstUuid).not.toEqual(secondUuid)
        expect(validateUuid(firstUuid)).toBe(true)
        expect(validateUuid(secondUuid)).toBe(true)
        expect(uuidVersion(firstUuid)).toBe(4)
        expect(uuidVersion(secondUuid)).toBe(4)
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.produce.mockRejectedValueOnce(error)

        const metadata = {
            sessionId: 'session123',
            teamId: 1,
            startTimestamp: 1000,
            endTimestamp: 2000,
            blockStartOffset: 0,
            blockLength: 100,
        }

        await expect(store.storeSessionBlock(metadata)).rejects.toThrow(error)
    })
})
