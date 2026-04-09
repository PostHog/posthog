import { KafkaProducerWrapper } from '../../kafka/producer'
import { DualWriteIngestionOutput } from './dual-write-ingestion-output'
import { IngestionOutputs } from './ingestion-outputs'
import { SingleIngestionOutput } from './single-ingestion-output'

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
                events: new SingleIngestionOutput('events', 'events', producer, 'test'),
                ai_events: new SingleIngestionOutput('ai_events', 'ai_events', producer, 'test'),
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual([])
            expect(producer.checkConnection).toHaveBeenCalledTimes(2)
        })

        it('checks each unique producer once', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'events', mskProducer, 'test'),
                ai_events: new SingleIngestionOutput('ai_events', 'ai_events', mskProducer, 'test'),
                heatmaps: new SingleIngestionOutput('heatmaps', 'heatmaps', wsProducer, 'test'),
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual([])
            expect(mskProducer.checkConnection).toHaveBeenCalledTimes(2)
            expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
        })

        it('returns failed output names when a producer is unreachable', async () => {
            const producer = createMockProducer()
            producer.checkConnection.mockRejectedValue(new Error('Connection refused'))
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'events', producer, 'test'),
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual(['events'])
        })

        it('returns failed output when one of multiple producers is unreachable', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            wsProducer.checkConnection.mockRejectedValue(new Error('WARPSTREAM unreachable'))

            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'events', mskProducer, 'test'),
                heatmaps: new SingleIngestionOutput('heatmaps', 'heatmaps', wsProducer, 'test'),
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual(['heatmaps'])
            expect(mskProducer.checkConnection).toHaveBeenCalledTimes(1)
            expect(wsProducer.checkConnection).toHaveBeenCalledTimes(1)
        })

        it('checks secondary producer in a dual-write output', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            const failures = await outputs.checkHealth()

            expect(failures).toEqual([])
            expect(primary.checkConnection).toHaveBeenCalledTimes(1)
            expect(secondary.checkConnection).toHaveBeenCalledTimes(1)
        })
    })

    describe('checkTopics', () => {
        it('returns empty array when all topics exist', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'events', producer, 'test'),
                ai_events: new SingleIngestionOutput('ai_events', 'ai_events', producer, 'test'),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledWith('events', 10000)
            expect(producer.checkTopicExists).toHaveBeenCalledWith('ai_events', 10000)
        })

        it('skips empty topics', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'events', producer, 'test'),
                redirect: new SingleIngestionOutput('redirect', '', producer, 'test'),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledTimes(1)
        })

        it('returns failed output when topic does not exist', async () => {
            const producer = createMockProducer()
            producer.checkTopicExists.mockRejectedValue(new Error('Topic not found'))
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'bad_topic', producer, 'test'),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual(['events'])
        })

        it('checks same topic separately on different producers', async () => {
            const mskProducer = createMockProducer()
            const wsProducer = createMockProducer()
            wsProducer.checkTopicExists.mockRejectedValue(new Error('Not found on warpstream'))

            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'shared_topic', mskProducer, 'test'),
                ai_events: new SingleIngestionOutput('ai_events', 'shared_topic', wsProducer, 'test'),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual(['ai_events'])
            expect(mskProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic', 10000)
            expect(wsProducer.checkTopicExists).toHaveBeenCalledWith('shared_topic', 10000)
        })

        it('checks same producer and topic independently per output', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'shared_topic', producer, 'test'),
                ai_events: new SingleIngestionOutput('ai_events', 'shared_topic', producer, 'test'),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(producer.checkTopicExists).toHaveBeenCalledTimes(2)
        })

        it('checks both topics in a dual-write output', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events_v1', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            const failures = await outputs.checkTopics()

            expect(failures).toEqual([])
            expect(primary.checkTopicExists).toHaveBeenCalledWith('events_v1', 10000)
            expect(secondary.checkTopicExists).toHaveBeenCalledWith('events_v2', 10000)
        })
    })

    describe('produce', () => {
        it('produces to the correct topic and producer', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'clickhouse_events', producer, 'test'),
            })

            await outputs.produce('events', { value: Buffer.from('test'), key: Buffer.from('key') })

            expect(producer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events',
                value: Buffer.from('test'),
                key: Buffer.from('key'),
            })
        })

        it('produces to all targets in a dual-write output', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events_v1', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            await outputs.produce('events', { value: Buffer.from('test'), key: Buffer.from('key') })

            expect(primary.produce).toHaveBeenCalledWith({
                topic: 'events_v1',
                value: Buffer.from('test'),
                key: Buffer.from('key'),
            })
            expect(secondary.produce).toHaveBeenCalledWith({
                topic: 'events_v2',
                value: Buffer.from('test'),
                key: Buffer.from('key'),
            })
        })

        it('rejects if any target in a dual-write fails', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            secondary.produce.mockRejectedValue(new Error('secondary broker down'))
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events_v1', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            await expect(
                outputs.produce('events', { value: Buffer.from('test'), key: Buffer.from('key') })
            ).rejects.toThrow('secondary broker down')

            expect(primary.produce).toHaveBeenCalledTimes(1)
            expect(secondary.produce).toHaveBeenCalledTimes(1)
        })
    })

    describe('queueMessages', () => {
        it('queues messages to the correct topic and producer', async () => {
            const producer = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'clickhouse_events', producer, 'test'),
            })

            await outputs.queueMessages('events', [{ value: Buffer.from('msg1') }, { value: Buffer.from('msg2') }])

            expect(producer.queueMessages).toHaveBeenCalledWith({
                topic: 'clickhouse_events',
                messages: [{ value: Buffer.from('msg1') }, { value: Buffer.from('msg2') }],
            })
        })

        it('queues messages to all targets in a dual-write output', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events_v1', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            await outputs.queueMessages('events', [{ value: Buffer.from('msg1') }])

            expect(primary.queueMessages).toHaveBeenCalledWith({
                topic: 'events_v1',
                messages: [{ value: Buffer.from('msg1') }],
            })
            expect(secondary.queueMessages).toHaveBeenCalledWith({
                topic: 'events_v2',
                messages: [{ value: Buffer.from('msg1') }],
            })
        })

        it('rejects if any target in a dual-write fails', async () => {
            const primary = createMockProducer()
            const secondary = createMockProducer()
            secondary.queueMessages.mockRejectedValue(new Error('secondary broker down'))
            const outputs = new IngestionOutputs({
                events: new DualWriteIngestionOutput(
                    new SingleIngestionOutput('events', 'events_v1', primary, 'test'),
                    new SingleIngestionOutput('events', 'events_v2', secondary, 'test')
                ),
            })

            await expect(outputs.queueMessages('events', [{ value: Buffer.from('msg1') }])).rejects.toThrow(
                'secondary broker down'
            )

            expect(primary.queueMessages).toHaveBeenCalledTimes(1)
            expect(secondary.queueMessages).toHaveBeenCalledTimes(1)
        })
    })
})
