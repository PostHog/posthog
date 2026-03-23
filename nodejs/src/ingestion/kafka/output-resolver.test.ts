import { KafkaProducerWrapper } from '../../kafka/producer'
import { IngestionOutputDefinition, resolveIngestionOutputs } from './output-resolver'
import { KafkaProducerRegistry } from './producer-registry'

describe('resolveIngestionOutputs', () => {
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

    function createMockRegistry(): KafkaProducerRegistry<'TEST_PRODUCER'> {
        const producer = createMockProducer()
        return {
            getProducer: jest.fn(async () => Promise.resolve(producer)),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry<'TEST_PRODUCER'>
    }

    const testDefinitions: Record<string, IngestionOutputDefinition<'TEST_PRODUCER'>> = {
        events: {
            defaultTopic: 'clickhouse_events',
            defaultProducerName: 'TEST_PRODUCER',
            producerOverrideEnvVar: 'TEST_EVENTS_PRODUCER',
            topicOverrideEnvVar: 'TEST_EVENTS_TOPIC',
        },
        ai_events: {
            defaultTopic: 'clickhouse_ai_events',
            defaultProducerName: 'TEST_PRODUCER',
            producerOverrideEnvVar: 'TEST_AI_EVENTS_PRODUCER',
            topicOverrideEnvVar: 'TEST_AI_EVENTS_TOPIC',
        },
    }

    it('resolves outputs with default topics and producers', async () => {
        const registry = createMockRegistry()

        const outputs = await resolveIngestionOutputs(registry, testDefinitions)

        expect(registry.getProducer).toHaveBeenCalledWith('TEST_PRODUCER')

        await outputs.queueMessages('events', [{ value: 'test' }])
        const producer = await registry.getProducer('TEST_PRODUCER')
        expect(producer.queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_events',
            messages: [{ value: 'test' }],
        })
    })

    it('overrides topic from env var', async () => {
        process.env.TEST_EVENTS_TOPIC = 'custom_events_topic'
        const registry = createMockRegistry()

        const outputs = await resolveIngestionOutputs(registry, testDefinitions)

        await outputs.queueMessages('events', [{ value: 'test' }])
        const producer = await registry.getProducer('TEST_PRODUCER')
        expect(producer.queueMessages).toHaveBeenCalledWith({
            topic: 'custom_events_topic',
            messages: [{ value: 'test' }],
        })
    })
})
