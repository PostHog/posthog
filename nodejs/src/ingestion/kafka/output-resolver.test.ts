import { KafkaProducerWrapper } from '../../kafka/producer'
import { resolveOutputs } from './output-resolver'
import { DEFAULT_PRODUCER } from './producer-definitions'
import { KafkaProducerRegistry } from './producer-registry'

describe('resolveOutputs', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    function createMockProducer(): KafkaProducerWrapper {
        return {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            checkConnection: jest.fn().mockResolvedValue(undefined),
            checkTopicExists: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper
    }

    function createMockRegistry(): KafkaProducerRegistry<typeof DEFAULT_PRODUCER> {
        const producer = createMockProducer()
        return {
            getProducer: jest.fn(async () => Promise.resolve(producer)),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry<typeof DEFAULT_PRODUCER>
    }

    it('resolves outputs with the correct topics and producers', async () => {
        const registry = createMockRegistry()

        const outputs = await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events', defaultProducerName: DEFAULT_PRODUCER },
            ai_events: { topic: 'clickhouse_ai_events', defaultProducerName: DEFAULT_PRODUCER },
        })

        expect(registry.getProducer).toHaveBeenCalledWith(DEFAULT_PRODUCER)

        await outputs.queueMessages('events', [{ value: 'test' }])
        const producer = await registry.getProducer(DEFAULT_PRODUCER)
        expect(producer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_events',
            messages: [{ value: 'test' }],
        })
    })

    it('uses defaultProducerName from definition', async () => {
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events', defaultProducerName: DEFAULT_PRODUCER },
        })

        expect(registry.getProducer).toHaveBeenCalledWith(DEFAULT_PRODUCER)
    })
})
