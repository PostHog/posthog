import { Message } from 'node-rdkafka'

import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-pipeline'
import { createContext, createNewBatchPipeline, createNewPipeline } from './helpers'
import { dlq, drop, ok, redirect } from './results'

describe('ConcurrentBatchProcessingPipeline', () => {
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
        it('should create instance with processor and previous pipeline', () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )
            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            expect(pipeline).toBeInstanceOf(ConcurrentBatchProcessingPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to previous pipeline', () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const previousPipeline = createNewBatchPipeline<string>().build()
            const spy = jest.spyOn(previousPipeline, 'feed')

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)
            const testBatch = [createContext(ok('test'), context1)]

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should process successful results concurrently', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )
            const previousPipeline = createNewBatchPipeline<string>().build()

            // Feed some test data
            const testBatch = [createContext(ok('hello'), context1), createContext(ok('world'), context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const result3 = await pipeline.next()

            expect(result1).toEqual([{ result: ok('HELLO'), context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: ok('WORLD'), context: expect.objectContaining({ message: message2 }) }])
            expect(result3).toBeNull()
        })

        it('should preserve non-success results without processing', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const dropResult = drop<string>('test drop')
            const dlqResult = dlq<string>('test dlq', new Error('test error'))
            const redirectResult = redirect<string>('test redirect', 'test-topic')

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch: BatchPipelineResultWithContext<string, any> = [
                createContext(dropResult, context1),
                createContext(dlqResult, context2),
                createContext(redirectResult, context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const result3 = await pipeline.next()
            const result4 = await pipeline.next()

            expect(result1).toEqual([{ result: dropResult, context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: dlqResult, context: expect.objectContaining({ message: message2 }) }])
            expect(result3).toEqual([
                { result: redirectResult, context: expect.objectContaining({ message: message3 }) },
            ])
            expect(result4).toBeNull()
        })

        it('should handle mixed success and non-success results', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )
            const dropResult = drop<string>('test drop')

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch: BatchPipelineResultWithContext<string, any> = [
                createContext(ok('hello'), context1),
                createContext(dropResult, context2),
                createContext(ok('world'), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const result3 = await pipeline.next()
            const result4 = await pipeline.next()

            expect(result1).toEqual([{ result: ok('HELLO'), context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: dropResult, context: expect.objectContaining({ message: message2 }) }])
            expect(result3).toEqual([{ result: ok('WORLD'), context: expect.objectContaining({ message: message3 }) }])
            expect(result4).toBeNull()
        })

        it('should handle async processing delays correctly', async () => {
            const processor = createNewPipeline<string>().pipe(async (input: string) => {
                // Simulate async delay
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok(input.toUpperCase())
            })

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [createContext(ok('fast'), context1), createContext(ok('slow'), context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            const startTime = Date.now()
            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const endTime = Date.now()

            expect(result1).toEqual([{ result: ok('FAST'), context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: ok('SLOW'), context: expect.objectContaining({ message: message2 }) }])
            // Both should complete around the same time due to concurrent processing
            expect(endTime - startTime).toBeLessThan(50) // Should be much less than 20ms
        })

        it('should handle processor errors gracefully', async () => {
            const processor = createNewPipeline<string>().pipe((_input: string) => {
                return Promise.reject(new Error('Processor error'))
            })

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [createContext(ok('test'), context1)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            await expect(pipeline.next()).rejects.toThrow('Processor error')
        })

        it('should process multiple batches sequentially', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )

            const previousPipeline = createNewBatchPipeline<string>().build()
            const batch1 = [createContext(ok('batch1'), context1)]
            const batch2 = [createContext(ok('batch2'), context2)]

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            // First batch: feed then next
            previousPipeline.feed(batch1)
            const result1 = await pipeline.next()
            expect(result1).toEqual([{ result: ok('BATCH1'), context: expect.objectContaining({ message: message1 }) }])

            // Second batch: feed then next
            previousPipeline.feed(batch2)
            const result2 = await pipeline.next()
            expect(result2).toEqual([{ result: ok('BATCH2'), context: expect.objectContaining({ message: message2 }) }])

            // Third call should return null
            const result3 = await pipeline.next()
            expect(result3).toBeNull()
        })

        it('should maintain promise queue state between calls', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('item1'), context1),
                createContext(ok('item2'), context2),
                createContext(ok('item3'), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            // First call should process first item
            const result1 = await pipeline.next()
            expect(result1).toEqual([{ result: ok('ITEM1'), context: expect.objectContaining({ message: message1 }) }])

            // Second call should process second item
            const result2 = await pipeline.next()
            expect(result2).toEqual([{ result: ok('ITEM2'), context: expect.objectContaining({ message: message2 }) }])

            // Third call should process third item
            const result3 = await pipeline.next()
            expect(result3).toEqual([{ result: ok('ITEM3'), context: expect.objectContaining({ message: message3 }) }])

            // Fourth call should return null
            const result4 = await pipeline.next()
            expect(result4).toBeNull()
        })
    })

    describe('concurrent processing behavior', () => {
        it('should process items concurrently within a batch', async () => {
            const processingOrder: string[] = []
            const processor = createNewPipeline<string>().pipe(async (input: string) => {
                processingOrder.push(`start-${input}`)
                // Simulate different processing times
                const delay = input === 'slow' ? 50 : 10
                await new Promise((resolve) => setTimeout(resolve, delay))
                processingOrder.push(`end-${input}`)
                return ok(input.toUpperCase())
            })

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('fast'), context1),
                createContext(ok('slow'), context2),
                createContext(ok('medium'), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentBatchProcessingPipeline(processor, previousPipeline)

            // Process the batch
            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const result3 = await pipeline.next()

            // Verify results
            expect(result1).toEqual([{ result: ok('FAST'), context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: ok('SLOW'), context: expect.objectContaining({ message: message2 }) }])
            expect(result3).toEqual([{ result: ok('MEDIUM'), context: expect.objectContaining({ message: message3 }) }])

            // Verify concurrent processing (all starts before any end)
            expect(processingOrder).toEqual([
                'start-fast',
                'start-slow',
                'start-medium',
                'end-fast',
                'end-medium',
                'end-slow',
            ])
        })
    })
})
