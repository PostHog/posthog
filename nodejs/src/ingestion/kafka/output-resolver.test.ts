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
        const eventsConfig = outputs.resolve('events')
        expect(eventsConfig.topic).toBe('clickhouse_events')

        const aiConfig = outputs.resolve('ai_events')
        expect(aiConfig.topic).toBe('clickhouse_ai_events')

        // Both outputs should use the same default producer
        expect(eventsConfig.producer).toBe(aiConfig.producer)
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

        // events should use MSK, ai_events should use default
        const eventsConfig = outputs.resolve('events')
        const aiConfig = outputs.resolve('ai_events')
        expect(eventsConfig.producer).not.toBe(aiConfig.producer)
    })

    it('uses defaultProducerName from definition when set', async () => {
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events', defaultProducerName: 'CUSTOM' },
        })

        expect(registry.getProducer).toHaveBeenCalledWith('CUSTOM')
    })

    it('always verifies broker connectivity', async () => {
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
        })

        const producer = (await registry.getProducer(undefined)) as jest.Mocked<KafkaProducerWrapper>
        expect(producer.checkConnection).toHaveBeenCalledTimes(1)
    })

    it('checks connectivity once per unique producer', async () => {
        const mskProducer = createMockProducer()
        const wsProducer = createMockProducer()

        const registry = {
            getProducer: jest.fn(async (name: string | undefined) => {
                if (name === 'MSK') {
                    return Promise.resolve(mskProducer)
                }
                if (name === 'WARPSTREAM') {
                    return Promise.resolve(wsProducer)
                }
                throw new Error(`Unknown producer: ${name}`)
            }),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry

        await resolveOutputs(registry, {
            events: { topic: 'events', defaultProducerName: 'MSK' },
            ai_events: { topic: 'ai_events', defaultProducerName: 'MSK' },
            heatmaps: { topic: 'heatmaps', defaultProducerName: 'WARPSTREAM' },
        })

        expect(mskProducer.checkConnection).toHaveBeenCalledTimes(1)
        expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
    })

    it('throws if broker is unreachable', async () => {
        const registry = createMockRegistry()
        const producer = await registry.getProducer(undefined)
        ;(producer.checkConnection as jest.Mock).mockRejectedValue(new Error('Connection refused'))

        await expect(
            resolveOutputs(registry, {
                events: { topic: 'clickhouse_events' },
            })
        ).rejects.toThrow('Connection refused')
    })

    it('throws if one of multiple brokers is unreachable', async () => {
        const mskProducer = createMockProducer()
        const wsProducer = createMockProducer()
        ;(wsProducer.checkConnection as jest.Mock).mockRejectedValue(new Error('WARPSTREAM broker unreachable'))

        const registry = {
            getProducer: jest.fn(async (name: string | undefined) => {
                if (name === 'MSK') {
                    return Promise.resolve(mskProducer)
                }
                if (name === 'WARPSTREAM') {
                    return Promise.resolve(wsProducer)
                }
                throw new Error(`Unknown producer: ${name}`)
            }),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry

        await expect(
            resolveOutputs(registry, {
                events: { topic: 'events', defaultProducerName: 'MSK' },
                heatmaps: { topic: 'heatmaps', defaultProducerName: 'WARPSTREAM' },
            })
        ).rejects.toThrow('WARPSTREAM broker unreachable')

        // MSK succeeded before WARPSTREAM failed
        expect(mskProducer.checkConnection).toHaveBeenCalledTimes(1)
        expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
    })

    it('does not verify topics by default', async () => {
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
        })

        const producer = (await registry.getProducer(undefined)) as jest.Mocked<KafkaProducerWrapper>
        expect(producer.checkTopicExists).not.toHaveBeenCalled()
    })

    it('verifies topics when INGESTION_OUTPUTS_VERIFY_TOPICS is set', async () => {
        process.env.INGESTION_OUTPUTS_VERIFY_TOPICS = 'true'
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
            ai_events: { topic: 'clickhouse_ai_events' },
        })

        const producer = (await registry.getProducer(undefined)) as jest.Mocked<KafkaProducerWrapper>
        expect(producer.checkTopicExists).toHaveBeenCalledWith('clickhouse_events')
        expect(producer.checkTopicExists).toHaveBeenCalledWith('clickhouse_ai_events')
    })

    it('skips verification for empty topics', async () => {
        process.env.INGESTION_OUTPUTS_VERIFY_TOPICS = 'true'
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'clickhouse_events' },
            redirect: { topic: '' },
        })

        const producer = (await registry.getProducer(undefined)) as jest.Mocked<KafkaProducerWrapper>
        expect(producer.checkTopicExists).toHaveBeenCalledTimes(1)
        expect(producer.checkTopicExists).toHaveBeenCalledWith('clickhouse_events')
    })

    it('throws if topic does not exist', async () => {
        process.env.INGESTION_OUTPUTS_VERIFY_TOPICS = 'true'
        const registry = createMockRegistry()
        const producer = await registry.getProducer(undefined)
        ;(producer.checkTopicExists as jest.Mock).mockRejectedValue(new Error('Topic "bad_topic" not found'))

        await expect(
            resolveOutputs(registry, {
                events: { topic: 'bad_topic' },
            })
        ).rejects.toThrow('Topic "bad_topic" not found')
    })

    it('checks same topic separately on different producers', async () => {
        process.env.INGESTION_OUTPUTS_VERIFY_TOPICS = 'true'
        const mskProducer = createMockProducer()
        const wsProducer = createMockProducer()
        ;(wsProducer.checkTopicExists as jest.Mock).mockRejectedValue(
            new Error('Topic "shared_topic" not found on warpstream')
        )

        const registry = {
            getProducer: jest.fn(async (name: string | undefined) => {
                if (name === 'MSK') {
                    return Promise.resolve(mskProducer)
                }
                if (name === 'WARPSTREAM') {
                    return Promise.resolve(wsProducer)
                }
                throw new Error(`Unknown producer: ${name}`)
            }),
            disconnectAll: jest.fn(),
        } as unknown as KafkaProducerRegistry

        await expect(
            resolveOutputs(registry, {
                events: { topic: 'shared_topic', defaultProducerName: 'MSK' },
                ai_events: { topic: 'shared_topic', defaultProducerName: 'WARPSTREAM' },
            })
        ).rejects.toThrow('Topic "shared_topic" not found on warpstream')

        // MSK check succeeded, WS check failed — both were called
        expect(mskProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic')
        expect(wsProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic')
    })

    it('deduplicates checks for same producer and topic', async () => {
        process.env.INGESTION_OUTPUTS_VERIFY_TOPICS = 'true'
        const registry = createMockRegistry()

        await resolveOutputs(registry, {
            events: { topic: 'shared_topic' },
            ai_events: { topic: 'shared_topic' },
        })

        const producer = (await registry.getProducer(undefined)) as jest.Mocked<KafkaProducerWrapper>
        expect(producer.checkTopicExists).toHaveBeenCalledTimes(1)
        expect(producer.checkTopicExists).toHaveBeenCalledWith('shared_topic')
    })
})
