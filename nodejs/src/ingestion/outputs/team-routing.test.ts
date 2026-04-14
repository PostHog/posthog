import { KafkaProducerWrapper } from '../../kafka/producer'
import { IngestionOutputs } from './ingestion-outputs'
import { KafkaProducerRegistry } from './kafka-producer-registry'
import { SingleIngestionOutput } from './single-ingestion-output'
import { applyTeamRouting, parseTeamIds } from './team-routing'

function createMockProducer(): jest.Mocked<KafkaProducerWrapper> {
    return {
        checkConnection: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<KafkaProducerWrapper>
}

describe('parseTeamIds', () => {
    it('parses comma-separated team IDs', () => {
        expect(parseTeamIds('1,2,3')).toEqual(new Set([1, 2, 3]))
    })

    it('handles whitespace', () => {
        expect(parseTeamIds(' 1 , 2 , 3 ')).toEqual(new Set([1, 2, 3]))
    })

    it('returns empty set for empty string', () => {
        expect(parseTeamIds('')).toEqual(new Set())
    })

    it('returns empty set for whitespace-only string', () => {
        expect(parseTeamIds('   ')).toEqual(new Set())
    })

    it('filters out NaN values', () => {
        expect(parseTeamIds('1,abc,3')).toEqual(new Set([1, 3]))
    })

    it('handles single value', () => {
        expect(parseTeamIds('42')).toEqual(new Set([42]))
    })
})

describe('applyTeamRouting', () => {
    it('returns outputs unchanged when teamIds is empty', () => {
        const producer = createMockProducer()
        const outputs = new IngestionOutputs({
            events: new SingleIngestionOutput('events', 'events_json', producer, 'DEFAULT'),
        })
        const registry = new KafkaProducerRegistry({ DEFAULT: producer } as Record<string, KafkaProducerWrapper>)

        const result = applyTeamRouting(outputs, registry, new Set(), 'WARPSTREAM', {})

        expect(result).toBe(outputs)
    })

    it('wraps outputs with TeamRoutedIngestionOutput when teamIds are set', async () => {
        const defaultProducer = createMockProducer()
        const wsProducer = createMockProducer()
        const outputs = new IngestionOutputs({
            events: new SingleIngestionOutput('events', 'events_json', defaultProducer, 'DEFAULT'),
        })
        const registry = new KafkaProducerRegistry({
            DEFAULT: defaultProducer,
            WARPSTREAM: wsProducer,
        } as Record<string, KafkaProducerWrapper>)

        const result = applyTeamRouting(outputs, registry, new Set([2]), 'WARPSTREAM', {
            INGESTION_OUTPUT_EVENTS_TOPIC: 'events_json',
        })

        // Produce for team 2 should go to WS
        await result.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 2 })
        expect(wsProducer.produce).toHaveBeenCalledTimes(1)
        expect(defaultProducer.produce).not.toHaveBeenCalled()

        // Produce for other teams should go to default
        defaultProducer.produce.mockClear()
        wsProducer.produce.mockClear()
        await result.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 99 })
        expect(defaultProducer.produce).toHaveBeenCalledTimes(1)
        expect(wsProducer.produce).not.toHaveBeenCalled()
    })

    it('uses the specified producer name', async () => {
        const defaultProducer = createMockProducer()
        const customProducer = createMockProducer()
        const outputs = new IngestionOutputs({
            events: new SingleIngestionOutput('events', 'events_json', defaultProducer, 'DEFAULT'),
        })
        const registry = new KafkaProducerRegistry({
            DEFAULT: defaultProducer,
            CUSTOM: customProducer,
        } as Record<string, KafkaProducerWrapper>)

        const result = applyTeamRouting(outputs, registry, new Set([2]), 'CUSTOM', {
            INGESTION_OUTPUT_EVENTS_TOPIC: 'events_json',
        })

        await result.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 2 })
        expect(customProducer.produce).toHaveBeenCalledTimes(1)
        expect(defaultProducer.produce).not.toHaveBeenCalled()
    })

    it('skips wrapping outputs without a topic in config', async () => {
        const defaultProducer = createMockProducer()
        const wsProducer = createMockProducer()
        const outputs = new IngestionOutputs({
            events: new SingleIngestionOutput('events', 'events_json', defaultProducer, 'DEFAULT'),
        })
        const registry = new KafkaProducerRegistry({
            DEFAULT: defaultProducer,
            WARPSTREAM: wsProducer,
        } as Record<string, KafkaProducerWrapper>)

        // No INGESTION_OUTPUT_EVENTS_TOPIC in config
        const result = applyTeamRouting(outputs, registry, new Set([2]), 'WARPSTREAM', {})

        // Should still go to default even for team 2 (not wrapped)
        await result.produce('events', { key: Buffer.from('k'), value: Buffer.from('v'), teamId: 2 })
        expect(defaultProducer.produce).toHaveBeenCalledTimes(1)
        expect(wsProducer.produce).not.toHaveBeenCalled()
    })
})
