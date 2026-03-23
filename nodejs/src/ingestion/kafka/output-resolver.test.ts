import { KafkaProducerWrapper } from '../../kafka/producer'
import { resolveOutputs } from './output-resolver'
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

    function createMockRegistry(): KafkaProducerRegistry {
        const producers = new Map<string, KafkaProducerWrapper>()
        const defaultProducer = createMockProducer()
        return {
            getProducer: jest.fn(async (name: string | undefined) => {
                if (name === undefined) {
                    return Promise.resolve(defaultProducer)
                }
                const normalized = name.toUpperCase()
                if (!producers.has(normalized)) {
                    producers.set(normalized, createMockProducer())
                }
                return Promise.resolve(producers.get(normalized)!)
            }),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry
    }

    it('uses default producer when no env vars or defaultProducerName are set', async () => {
        const registry = createMockRegistry()

        const outputs = await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
            ai_events: { topic: 'clickhouse_ai_events' },
        })

        expect(registry.getProducer).toHaveBeenCalledWith(undefined)

        // Verify outputs produce to the correct topics
        await outputs.queueMessages('events', [{ value: 'test' }])
        const producer = await registry.getProducer(undefined)
        expect(producer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_events',
            messages: [{ value: 'test' }],
        })
    })

    it('overrides producer name from env var', async () => {
        process.env.INGESTION_OUTPUT_EVENTS_PRODUCER = 'MSK'
        const registry = createMockRegistry()

        const outputs = await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
            ai_events: { topic: 'clickhouse_ai_events' },
        })

        expect(registry.getProducer).toHaveBeenCalledWith('MSK')
        expect(registry.getProducer).toHaveBeenCalledWith(undefined)

        // Verify events goes through the MSK producer, ai_events through the default
        const mskProducer = await registry.getProducer('MSK')
        const defaultProducer = await registry.getProducer(undefined)

        await outputs.queueMessages('events', [{ value: 'test' }])
        expect(mskProducer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_events',
            messages: [{ value: 'test' }],
        })
        expect(defaultProducer.queueMessages).not.toHaveBeenCalled()

        await outputs.queueMessages('ai_events', [{ value: 'test2' }])
        expect(defaultProducer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_ai_events',
            messages: [{ value: 'test2' }],
        })
    })

    it('uses defaultProducerName from definition when set', async () => {
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events', defaultProducerName: 'CUSTOM' },
        })

        expect(registry.getProducer).toHaveBeenCalledWith('CUSTOM')
    })
})
