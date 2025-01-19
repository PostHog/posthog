import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { getParsedQueuedMessages, mockProducer } from '../../tests/helpers/mocks/producer.mock'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { IngestionConsumer } from './ingestion-consumer'

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.setTimeout(1000)

type DecodedKafkaMessage = {
    topic: string
    key?: any
    value: Record<string, unknown>
}

const decodeAllKafkaMessages = (): DecodedKafkaMessage[] => {
    const queuedMessages = getParsedQueuedMessages()

    const result: DecodedKafkaMessage[] = []

    for (const topicMessage of queuedMessages) {
        for (const message of topicMessage.messages) {
            result.push({
                topic: topicMessage.topic,
                key: message.key,
                value: message.value ?? {},
            })
        }
    }

    return result
}

describe('IngestionConsumer', () => {
    let processor: IngestionConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        hub.kafkaProducer = mockProducer
        team = await getFirstTeam(hub)

        processor = new IngestionConsumer(hub)
        await processor.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general', () => {
        beforeEach(async () => {})

        it('should process events', () => {
            expect(1).toEqual(2)
        })
    })
})
