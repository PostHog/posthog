import { Message } from 'node-rdkafka'

import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BufferingBatchPipeline } from './buffering-batch-pipeline'
import { dlq, drop, ok, redirect } from './results'

describe('BufferingBatchPipeline', () => {
    let message1: Message
    let message2: Message
    let message3: Message
    let context1: { message: Message }
    let context2: { message: Message }
    let context3: { message: Message }

    beforeEach(() => {
        // Create different mock messages with unique properties
        message1 = {
            topic: 'test-topic',
            partition: 0,
            offset: 1,
            key: Buffer.from('key1'),
            value: Buffer.from('value1'),
            timestamp: Date.now(),
        } as Message

        message2 = {
            topic: 'test-topic',
            partition: 0,
            offset: 2,
            key: Buffer.from('key2'),
            value: Buffer.from('value2'),
            timestamp: Date.now() + 1,
        } as Message

        message3 = {
            topic: 'test-topic',
            partition: 0,
            offset: 3,
            key: Buffer.from('key3'),
            value: Buffer.from('value3'),
            timestamp: Date.now() + 2,
        } as Message

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
    })

    describe('constructor', () => {
        it('should create instance with default type', () => {
            const pipeline = new BufferingBatchPipeline()
            expect(pipeline).toBeInstanceOf(BufferingBatchPipeline)
        })

        it('should create instance with custom type', () => {
            const pipeline = new BufferingBatchPipeline<string>()
            expect(pipeline).toBeInstanceOf(BufferingBatchPipeline)
        })
    })

    describe('feed', () => {
        it('should add elements to buffer', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const batch: BatchPipelineResultWithContext<string> = [
                { result: ok('hello'), context: context1 },
                { result: ok('world'), context: context2 },
            ]

            pipeline.feed(batch)

            // Buffer is internal, so we test through next()
            const result = await pipeline.next()
            expect(result).toEqual([
                { result: ok('hello'), context: context1 },
                { result: ok('world'), context: context2 },
            ])
        })

        it('should accumulate multiple feeds', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const batch1: BatchPipelineResultWithContext<string> = [{ result: ok('hello'), context: context1 }]
            const batch2: BatchPipelineResultWithContext<string> = [{ result: ok('world'), context: context2 }]

            pipeline.feed(batch1)
            pipeline.feed(batch2)

            const result = await pipeline.next()
            expect(result).toEqual([
                { result: ok('hello'), context: context1 },
                { result: ok('world'), context: context2 },
            ])
        })

        it('should handle empty batch', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const emptyBatch: BatchPipelineResultWithContext<string> = []

            pipeline.feed(emptyBatch)

            const result = await pipeline.next()
            expect(result).toEqual(null)
        })
    })

    describe('next', () => {
        it('should return null when buffer is empty', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should return all buffered elements and clear buffer', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const batch: BatchPipelineResultWithContext<string> = [
                { result: ok('hello'), context: context1 },
                { result: ok('world'), context: context2 },
            ]

            pipeline.feed(batch)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()

            expect(result1).toEqual([
                { result: ok('hello'), context: context1 },
                { result: ok('world'), context: context2 },
            ])
            expect(result2).toBeNull()
        })

        it('should handle mixed result types', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const dropResult = drop<string>('test drop')
            const dlqResult = dlq<string>('test dlq', new Error('test error'))
            const redirectResult = redirect<string>('test redirect', 'test-topic')

            const batch: BatchPipelineResultWithContext<string> = [
                { result: ok('hello'), context: context1 },
                { result: dropResult, context: context2 },
                { result: dlqResult, context: context3 },
                { result: redirectResult, context: context1 },
            ]

            pipeline.feed(batch)

            const result = await pipeline.next()
            const result2 = await pipeline.next()

            expect(result).toEqual([
                { result: ok('hello'), context: context1 },
                { result: dropResult, context: context2 },
                { result: dlqResult, context: context3 },
                { result: redirectResult, context: context1 },
            ])
            expect(result2).toBeNull()
        })

        it('should preserve order of fed elements', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const batch1: BatchPipelineResultWithContext<string> = [{ result: ok('first'), context: context1 }]
            const batch2: BatchPipelineResultWithContext<string> = [{ result: ok('second'), context: context2 }]
            const batch3: BatchPipelineResultWithContext<string> = [{ result: ok('third'), context: context3 }]

            pipeline.feed(batch1)
            pipeline.feed(batch2)
            pipeline.feed(batch3)

            const result = await pipeline.next()
            const result2 = await pipeline.next()

            expect(result).toEqual([
                { result: ok('first'), context: context1 },
                { result: ok('second'), context: context2 },
                { result: ok('third'), context: context3 },
            ])
            expect(result2).toBeNull()
        })

        it('should handle large number of elements', async () => {
            const pipeline = new BufferingBatchPipeline<string>()
            const batch: BatchPipelineResultWithContext<string> = []

            for (let i = 0; i < 100; i++) {
                batch.push({ result: ok(`item${i}`), context: context1 })
            }

            pipeline.feed(batch)

            const result = await pipeline.next()
            const result2 = await pipeline.next()

            expect(result).toHaveLength(100)
            expect(result![0]).toEqual({ result: ok('item0'), context: context1 })
            expect(result![99]).toEqual({ result: ok('item99'), context: context1 })
            expect(result2).toBeNull()
        })

        it('should resume after returning null when more elements are fed', async () => {
            const pipeline = new BufferingBatchPipeline<string>()

            // First round: feed and process
            const batch1: BatchPipelineResultWithContext<string> = [{ result: ok('first'), context: context1 }]
            pipeline.feed(batch1)

            const result1 = await pipeline.next()
            expect(result1).toEqual([{ result: ok('first'), context: context1 }])

            // Should return null when buffer is empty
            const result2 = await pipeline.next()
            expect(result2).toBeNull()

            // Feed more elements
            const batch2: BatchPipelineResultWithContext<string> = [{ result: ok('second'), context: context2 }]
            pipeline.feed(batch2)

            // Should resume processing
            const result3 = await pipeline.next()
            expect(result3).toEqual([{ result: ok('second'), context: context2 }])

            // Should return null again
            const result4 = await pipeline.next()
            expect(result4).toBeNull()
        })
    })
})
