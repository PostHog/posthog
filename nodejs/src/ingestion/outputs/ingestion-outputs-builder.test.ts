import { KafkaProducerWrapper } from '../../kafka/producer'
import { IngestionOutputsBuilder, parseTeamDenylist } from './ingestion-outputs-builder'
import { KafkaProducerRegistry } from './kafka-producer-registry'

describe('IngestionOutputsBuilder', () => {
    type TestProducer = 'PRIMARY' | 'SECONDARY'

    function createMockProducer(): KafkaProducerWrapper {
        return {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            checkConnection: jest.fn().mockResolvedValue(undefined),
            checkTopicExists: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper
    }

    function createRegistry(): KafkaProducerRegistry<TestProducer> {
        return new KafkaProducerRegistry({
            PRIMARY: createMockProducer(),
            SECONDARY: createMockProducer(),
        })
    }

    it('builds outputs from config values', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'clickhouse_events',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
        }

        const outputs = new IngestionOutputsBuilder()
            .register('events', { topicKey: 'EVENTS_TOPIC', producerKey: 'EVENTS_PRODUCER' })
            .build(registry, config)

        await outputs.queueMessages('events', [{ value: Buffer.from('test') }])
        expect(registry.getProducer('PRIMARY').queueMessages).toHaveBeenCalledWith({
            topic: 'clickhouse_events',
            messages: [{ value: Buffer.from('test') }],
        })
    })

    it('routes different outputs to different producers', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_topic',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            DLQ_TOPIC: 'dlq_topic',
            DLQ_PRODUCER: 'SECONDARY' as TestProducer,
        }

        const outputs = new IngestionOutputsBuilder()
            .register('events', { topicKey: 'EVENTS_TOPIC', producerKey: 'EVENTS_PRODUCER' })
            .register('dlq', { topicKey: 'DLQ_TOPIC', producerKey: 'DLQ_PRODUCER' })
            .build(registry, config)

        await outputs.queueMessages('events', [{ value: Buffer.from('event') }])
        await outputs.queueMessages('dlq', [{ value: Buffer.from('dead') }])

        expect(registry.getProducer('PRIMARY').queueMessages).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_topic' })
        )
        expect(registry.getProducer('SECONDARY').queueMessages).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'dlq_topic' })
        )
    })

    it('uses config values as topics directly (no fallback logic)', async () => {
        const registry = createRegistry()
        const config = {
            MY_TOPIC: 'custom_topic_name',
            MY_PRODUCER: 'PRIMARY' as TestProducer,
        }

        const outputs = new IngestionOutputsBuilder()
            .register('output', { topicKey: 'MY_TOPIC', producerKey: 'MY_PRODUCER' })
            .build(registry, config)

        await outputs.produce('output', { key: Buffer.from('k'), value: Buffer.from('v') })
        expect(registry.getProducer('PRIMARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'custom_topic_name' })
        )
    })

    it('builds empty outputs when nothing is registered', async () => {
        const registry = createRegistry()
        const outputs = new IngestionOutputsBuilder().build(registry, {})

        await expect(outputs.checkHealth()).resolves.toEqual([])
    })

    it('chaining preserves earlier registrations', async () => {
        const registry = createRegistry()
        const config = {
            A_TOPIC: 'topic_a',
            A_PRODUCER: 'PRIMARY' as TestProducer,
            B_TOPIC: 'topic_b',
            B_PRODUCER: 'PRIMARY' as TestProducer,
        }

        const builder = new IngestionOutputsBuilder().register('a', { topicKey: 'A_TOPIC', producerKey: 'A_PRODUCER' })

        const outputs = builder
            .register('b', { topicKey: 'B_TOPIC', producerKey: 'B_PRODUCER' })
            .build(registry, config)

        await outputs.queueMessages('a', [{ value: Buffer.from('a') }])
        await outputs.queueMessages('b', [{ value: Buffer.from('b') }])

        expect(registry.getProducer('PRIMARY').queueMessages).toHaveBeenCalledTimes(2)
    })

    it('earlier builder is not mutated by later registrations', async () => {
        const registry = createRegistry()

        const builderA = new IngestionOutputsBuilder().register('a', { topicKey: 'A_TOPIC', producerKey: 'A_PRODUCER' })

        // Forking builderA with a new registration must not mutate builderA.
        // The return value is intentionally discarded — we only care that builderA is unchanged.
        builderA.register('b', { topicKey: 'B_TOPIC', producerKey: 'B_PRODUCER' })

        const config = {
            A_TOPIC: 'topic_a',
            A_PRODUCER: 'PRIMARY' as TestProducer,
        }

        const outputs = builderA.build(registry, config)

        await outputs.queueMessages('a', [{ value: Buffer.from('a') }])
        expect(registry.getProducer('PRIMARY').queueMessages).toHaveBeenCalledTimes(1)
    })

    it('dual write in copy mode fans out to both producers', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'copy',
            EVENTS_PERCENTAGE: 100,
        }

        const outputs = new IngestionOutputsBuilder()
            .registerDualWrite('events', {
                topicKey: 'EVENTS_TOPIC',
                producerKey: 'EVENTS_PRODUCER',
                secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                modeKey: 'EVENTS_MODE',
                percentageKey: 'EVENTS_PERCENTAGE',
            })
            .build(registry, config)

        await outputs.produce('events', { key: Buffer.from('k'), value: Buffer.from('v') })

        expect(registry.getProducer('PRIMARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v1' })
        )
        expect(registry.getProducer('SECONDARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v2' })
        )
    })

    it('dual write in off mode falls back to single output', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'off',
            EVENTS_PERCENTAGE: 100,
        }

        const outputs = new IngestionOutputsBuilder()
            .registerDualWrite('events', {
                topicKey: 'EVENTS_TOPIC',
                producerKey: 'EVENTS_PRODUCER',
                secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                modeKey: 'EVENTS_MODE',
                percentageKey: 'EVENTS_PERCENTAGE',
            })
            .build(registry, config)

        await outputs.produce('events', { key: Buffer.from('k'), value: Buffer.from('v') })

        expect(registry.getProducer('PRIMARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v1' })
        )
        expect(registry.getProducer('SECONDARY').produce).not.toHaveBeenCalled()
    })

    it('dual write in move_team_denylist mode routes by teamId', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'move_team_denylist',
            EVENTS_PERCENTAGE: 0,
            EVENTS_TEAM_DENYLIST: '42,99',
        }

        const outputs = new IngestionOutputsBuilder()
            .registerDualWriteWithDenylist('events', {
                topicKey: 'EVENTS_TOPIC',
                producerKey: 'EVENTS_PRODUCER',
                secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                modeKey: 'EVENTS_MODE',
                percentageKey: 'EVENTS_PERCENTAGE',
                teamDenylistKey: 'EVENTS_TEAM_DENYLIST',
            })
            .build(registry, config)

        // denied team → primary
        await outputs.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 42 })
        expect(registry.getProducer('PRIMARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v1' })
        )
        expect(registry.getProducer('SECONDARY').produce).not.toHaveBeenCalled()

        // allowed team → secondary only
        await outputs.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 7 })
        expect(registry.getProducer('SECONDARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v2' })
        )
    })

    it('throws when a denylist mode is configured without teamDenylistKey', () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'move_team_denylist',
            EVENTS_PERCENTAGE: 0,
        }

        expect(() =>
            new IngestionOutputsBuilder()
                .registerDualWrite('events', {
                    topicKey: 'EVENTS_TOPIC',
                    producerKey: 'EVENTS_PRODUCER',
                    secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                    secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                    modeKey: 'EVENTS_MODE',
                    percentageKey: 'EVENTS_PERCENTAGE',
                })
                .build(registry, config)
        ).toThrow(/teamDenylistKey/)
    })

    it('throws when a denylist mode is configured with an empty denylist', () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'move_team_denylist',
            EVENTS_PERCENTAGE: 0,
            EVENTS_TEAM_DENYLIST: '',
        }

        expect(() =>
            new IngestionOutputsBuilder()
                .registerDualWriteWithDenylist('events', {
                    topicKey: 'EVENTS_TOPIC',
                    producerKey: 'EVENTS_PRODUCER',
                    secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                    secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                    modeKey: 'EVENTS_MODE',
                    percentageKey: 'EVENTS_PERCENTAGE',
                    teamDenylistKey: 'EVENTS_TEAM_DENYLIST',
                })
                .build(registry, config)
        ).toThrow(/team denylist is empty/)
    })

    it('mixes register and registerDualWrite', async () => {
        const registry = createRegistry()
        const config = {
            EVENTS_TOPIC: 'events_v1',
            EVENTS_PRODUCER: 'PRIMARY' as TestProducer,
            EVENTS_SECONDARY_TOPIC: 'events_v2',
            EVENTS_SECONDARY_PRODUCER: 'SECONDARY' as TestProducer,
            EVENTS_MODE: 'copy',
            EVENTS_PERCENTAGE: 100,
            DLQ_TOPIC: 'dlq_topic',
            DLQ_PRODUCER: 'PRIMARY' as TestProducer,
        }

        const outputs = new IngestionOutputsBuilder()
            .registerDualWrite('events', {
                topicKey: 'EVENTS_TOPIC',
                producerKey: 'EVENTS_PRODUCER',
                secondaryTopicKey: 'EVENTS_SECONDARY_TOPIC',
                secondaryProducerKey: 'EVENTS_SECONDARY_PRODUCER',
                modeKey: 'EVENTS_MODE',
                percentageKey: 'EVENTS_PERCENTAGE',
            })
            .register('dlq', { topicKey: 'DLQ_TOPIC', producerKey: 'DLQ_PRODUCER' })
            .build(registry, config)

        await outputs.produce('events', { key: Buffer.from('k'), value: Buffer.from('v') })
        await outputs.queueMessages('dlq', [{ value: Buffer.from('dead') }])

        // events fans out to both
        expect(registry.getProducer('PRIMARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v1' })
        )
        expect(registry.getProducer('SECONDARY').produce).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'events_v2' })
        )
        // dlq goes to primary only
        expect(registry.getProducer('PRIMARY').queueMessages).toHaveBeenCalledWith(
            expect.objectContaining({ topic: 'dlq_topic' })
        )
    })
})

describe('parseTeamDenylist', () => {
    it('returns empty set for empty string', () => {
        expect(parseTeamDenylist('')).toEqual(new Set())
    })

    it('returns empty set for whitespace-only string', () => {
        expect(parseTeamDenylist('   ')).toEqual(new Set())
    })

    it('parses comma-separated ids', () => {
        expect(parseTeamDenylist('1,2,3')).toEqual(new Set([1, 2, 3]))
    })

    it('trims whitespace around ids', () => {
        expect(parseTeamDenylist(' 1 , 2 , 3 ')).toEqual(new Set([1, 2, 3]))
    })

    it('skips non-numeric entries', () => {
        expect(parseTeamDenylist('1,abc,3')).toEqual(new Set([1, 3]))
    })

    it('rejects mixed tokens instead of truncating', () => {
        // parseInt('1234abc', 10) would silently yield 1234 — we want this rejected.
        expect(parseTeamDenylist('1234abc,42')).toEqual(new Set([42]))
    })

    it('skips empty entries from double commas', () => {
        expect(parseTeamDenylist('1,,2')).toEqual(new Set([1, 2]))
    })

    it('deduplicates repeated ids', () => {
        expect(parseTeamDenylist('1,1,2')).toEqual(new Set([1, 2]))
    })
})
