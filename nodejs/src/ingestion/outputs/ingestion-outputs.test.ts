import { KafkaProducerWrapper } from '../../kafka/producer'
import { IngestionOutputs } from './ingestion-outputs'

function createMockProducer(): jest.Mocked<KafkaProducerWrapper> {
    return {
        checkConnection: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<KafkaProducerWrapper>
}

describe('IngestionOutputs', () => {
    describe('checkHealth', () => {
        it('returns empty array when all producers are healthy', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer },
                ai_events: { topic: 'ai_events', producer },
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual([])
            expect(producer.checkConnection).toHaveBeenCalledTimes(1)
        })

        it('checks each unique producer once', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer: mskProducer },
                ai_events: { topic: 'ai_events', producer: mskProducer },
                heatmaps: { topic: 'heatmaps', producer: wsProducer },
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual([])
            expect(mskProducer.checkConnection).toHaveBeenCalledTimes(1)
            expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
        })

        it('returns failed output names when a producer is unreachable', async () => {
            const producer = createMockProducer()
            producer.checkConnection.mockRejectedValue(new Error('Connection refused'))
            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer },
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual(['events'])
        })

        it('returns failed output when one of multiple producers is unreachable', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            wsProducer.checkConnection.mockRejectedValue(new Error('WARPSTREAM unreachable'))

            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer: mskProducer },
                heatmaps: { topic: 'heatmaps', producer: wsProducer },
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual(['heatmaps'])
            expect(mskProducer.checkConnection).toHaveBeenCalledTimes(1)
            expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
        })
    })

    describe('checkTopics', () => {
        it('returns empty array when all topics exist', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer },
                ai_events: { topic: 'ai_events', producer },
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledWith('events', 10000)
            expect(producer.checkTopicExists).toHaveBeenCalledWith('ai_events', 10000)
        })

        it('skips empty topics', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'events', producer },
                redirect: { topic: '', producer },
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledTimes(1)
        })

        it('returns failed output when topic does not exist', async () => {
            const producer = createMockProducer()
            producer.checkTopicExists.mockRejectedValue(new Error('Topic not found'))
            const outputs = new IngestionOutputs({
                events: { topic: 'bad_topic', producer },
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual(['events'])
        })

        it('checks same topic separately on different producers', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            wsProducer.checkTopicExists.mockRejectedValue(new Error('Not found on warpstream'))

            const outputs = new IngestionOutputs({
                events: { topic: 'shared_topic', producer: mskProducer },
                ai_events: { topic: 'shared_topic', producer: wsProducer },
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual(['ai_events'])
            expect(mskProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic', 10000)
            expect(wsProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic', 10000)
        })

        it('deduplicates same producer and topic', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'shared_topic', producer },
                ai_events: { topic: 'shared_topic', producer },
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledTimes(1)
        })
    })

    describe('produce', () => {
        it('produces to the correct topic and producer', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'clickhouse_events', producer },
            })

            await outputs.produce('events', { value: Buffer.from('test'), key: Buffer.from('key') })

            expect(producer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events',
                value: Buffer.from('test'),
                key: Buffer.from('key'),
            })
        })
    })

    describe('queueMessages', () => {
        it('queues messages to the correct topic and producer', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: { topic: 'clickhouse_events', producer },
            })

            await outputs.queueMessages('events', [{ value: Buffer.from('msg1') }, { value: Buffer.from('msg2') }])

            expect(producer.queueMessages).toHaveBeenCalledWith({
                topic: 'clickhouse_events',
                messages: [{ value: Buffer.from('msg1') }, { value: Buffer.from('msg2') }],
            })
        })
    })
})
