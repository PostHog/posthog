import { Message } from 'node-rdkafka'

import { createMockPipeline } from '~/tests/helpers/mock-pipeline'

import { ConcurrentChunkProcessingPipeline } from './concurrent-chunk-pipeline'
import { createContext, createNewChunkPipeline, createNewPipeline, createOkContext } from './helpers'
import { dlq, drop, ok } from './results'

describe('ConcurrentChunkProcessingPipeline', () => {
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
            const previousPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            expect(pipeline).toBeInstanceOf(ConcurrentChunkProcessingPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to previous pipeline', () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const previousPipeline = createNewChunkPipeline<string>().build()
            const spy = jest.spyOn(previousPipeline, 'feed')

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)
            const testBatch = [createOkContext('test', context1)]

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const previousPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should process successful results concurrently', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )
            const previousPipeline = createNewChunkPipeline<string>().build()

            // Feed some test data
            const testBatch = [createOkContext('hello', context1), createOkContext('world', context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

            const testBatch = [createContext(dropResult, context1), createContext(dlqResult, context2)]
            const previousPipeline = createMockPipeline<string>(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()
            const result3 = await pipeline.next()

            expect(result1).toEqual([{ result: dropResult, context: expect.objectContaining({ message: message1 }) }])
            expect(result2).toEqual([{ result: dlqResult, context: expect.objectContaining({ message: message2 }) }])
            expect(result3).toBeNull()
        })

        it('should handle mixed success and non-success results', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )
            const dropResult = drop<string>('test drop')

            const testBatch = [
                createOkContext('hello', context1),
                createContext(dropResult, context2),
                createOkContext('world', context3),
            ]
            const previousPipeline = createMockPipeline<string>(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = [createOkContext('fast', context1), createOkContext('slow', context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = [createOkContext('test', context1)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            await expect(pipeline.next()).rejects.toThrow('Processor error')
        })

        it('should process multiple batches sequentially', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) =>
                Promise.resolve(ok(input.toUpperCase()))
            )

            const previousPipeline = createNewChunkPipeline<string>().build()
            const batch1 = [createOkContext('batch1', context1)]
            const batch2 = [createOkContext('batch2', context2)]

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = [
                createOkContext('item1', context1),
                createOkContext('item2', context2),
                createOkContext('item3', context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = [
                createOkContext('fast', context1),
                createOkContext('slow', context2),
                createOkContext('medium', context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

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

        it('caps how many items process at once when maxConcurrency is set', async () => {
            const itemCount = 6
            const maxConcurrency = 2
            let active = 0
            let peak = 0

            const processor = createNewPipeline<string>().pipe(async (input: string) => {
                active++
                peak = Math.max(peak, active)
                await new Promise((resolve) => setTimeout(resolve, 5))
                active--
                return ok(input.toUpperCase())
            })
            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = Array.from({ length: itemCount }, (_, i) => createOkContext(`item-${i}`, context1))
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline, maxConcurrency)

            const results = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(itemCount)
            // Reached the cap (proves it's concurrent) but never exceeded it.
            expect(peak).toBe(maxConcurrency)
        })

        it('emits in FIFO order under a cap even when a slow head finishes last', async () => {
            // More items than permits (cap 2, 4 items) so later items must park for a
            // permit, and the head is the slowest so completion order (1,2,3,0) diverges
            // from input order. p-limit's FIFO wait queue must still hand the head its
            // permit first; emission then stays in input order regardless of durations.
            const delaysByIndex = [30, 5, 5, 5]
            const processor = createNewPipeline<string>().pipe(async (input: string) => {
                const index = Number(input.split('-')[1])
                await new Promise((resolve) => setTimeout(resolve, delaysByIndex[index]))
                return ok(input.toUpperCase())
            })
            const previousPipeline = createNewChunkPipeline<string>().build()
            const testBatch = delaysByIndex.map((_, i) => createOkContext(`item-${i}`, context1))
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline, 2)

            const emitted = []
            let result = await pipeline.next()
            while (result !== null) {
                emitted.push(...result.map((r) => r.result))
                result = await pipeline.next()
            }

            expect(emitted).toEqual([ok('ITEM-0'), ok('ITEM-1'), ok('ITEM-2'), ok('ITEM-3')])
        })
    })

    describe('error poisoning', () => {
        it('poisons permanently after a source error', async () => {
            const processor = createNewPipeline<string>().pipe((input: string) => Promise.resolve(ok(input)))
            const previousPipeline = {
                feed: jest.fn(),
                next: jest.fn().mockRejectedValueOnce(new Error('source boom')).mockResolvedValue(null),
            }
            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            await expect(pipeline.next()).rejects.toThrow('source boom')
            await expect(pipeline.next()).rejects.toThrow('source boom')
        })

        it('drains in-flight items after a processing error, then poisons', async () => {
            const processor = createNewPipeline<{ value: string; fail?: boolean }>().pipe((input) =>
                input.fail ? Promise.reject(new Error('item boom')) : Promise.resolve(ok(input))
            )
            const previousPipeline = createNewChunkPipeline<{ value: string; fail?: boolean }>().build()
            const pipeline = new ConcurrentChunkProcessingPipeline(processor, previousPipeline)

            // FIFO: the failing head surfaces first, the already in-flight item
            // drains next, then the stage rejects permanently.
            previousPipeline.feed([
                createOkContext({ value: 'i1', fail: true }, context1),
                createOkContext({ value: 'i2' }, context2),
            ])

            await expect(pipeline.next()).rejects.toThrow('item boom')
            expect(await pipeline.next()).toEqual([
                { result: ok({ value: 'i2' }), context: expect.objectContaining({ message: message2 }) },
            ])
            await expect(pipeline.next()).rejects.toThrow('item boom')
        })
    })
})
