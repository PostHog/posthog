import { Message } from 'node-rdkafka'

import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { GatheringBatchPipeline } from './gathering-batch-pipeline'
import { createContext, createNewBatchPipeline } from './helpers'
import { dlq, drop, ok, redirect } from './results'

// Mock batch processing pipeline for testing
class MockBatchProcessingPipeline<T, C> implements BatchPipeline<T, T, C> {
    private results: BatchPipelineResultWithContext<T, C>[] = []
    private currentIndex = 0

    constructor(results: BatchPipelineResultWithContext<T, C>[]) {
        this.results = results
    }

    feed(elements: BatchPipelineResultWithContext<T, C>): void {
        this.results.push(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<T, C> | null> {
        if (this.currentIndex >= this.results.length) {
            return Promise.resolve(null)
        }
        return Promise.resolve(this.results[this.currentIndex++])
    }
}

describe('GatheringBatchPipeline', () => {
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
        it('should create instance with sub-pipeline', () => {
            const subPipeline = createNewBatchPipeline<string>().build()
            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            expect(gatherPipeline).toBeInstanceOf(GatheringBatchPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to sub-pipeline', () => {
            const subPipeline = createNewBatchPipeline<string>().build()
            const spy = jest.spyOn(subPipeline, 'feed')
            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const testBatch = [createContext(ok('test'), context1)]

            gatherPipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const subPipeline = createNewBatchPipeline<string>().build()
            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            expect(result).toBeNull()
        })

        it('should gather all results from sub-pipeline in single call', async () => {
            const subPipeline = new MockBatchProcessingPipeline([
                [createContext(ok('hello'), context1)],
                [createContext(ok('world'), context2)],
                [createContext(ok('test'), context3)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('hello'), context1),
                createContext(ok('world'), context2),
                createContext(ok('test'), context3),
            ])
            expect(result2).toBeNull()
        })

        it('should preserve non-success results', async () => {
            const dropResult = drop<string>('test drop')
            const dlqResult = dlq<string>('test dlq', new Error('test error'))
            const redirectResult = redirect<string>('test redirect', 'test-topic')

            const subPipeline = new MockBatchProcessingPipeline([
                [createContext(dropResult, context1)],
                [createContext(dlqResult, context2)],
                [createContext(redirectResult, context3)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(dropResult, context1),
                createContext(dlqResult, context2),
                createContext(redirectResult, context3),
            ])
            expect(result2).toBeNull()
        })

        it('should handle mixed success and non-success results', async () => {
            const dropResult = drop<string>('test drop')

            const subPipeline = new MockBatchProcessingPipeline([
                [createContext(ok('hello'), context1)],
                [createContext(dropResult, context2)],
                [createContext(ok('world'), context3)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('hello'), context1),
                createContext(dropResult, context2),
                createContext(ok('world'), context3),
            ])
            expect(result2).toBeNull()
        })

        it('should handle empty batches from sub-pipeline', async () => {
            const subPipeline = new MockBatchProcessingPipeline([
                [], // Empty batch
                [createContext(ok('hello'), context1)],
                [], // Another empty batch
                [createContext(ok('world'), context2)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([createContext(ok('hello'), context1), createContext(ok('world'), context2)])
            expect(result2).toBeNull()
        })

        it('should return null when all batches are empty', async () => {
            const subPipeline = new MockBatchProcessingPipeline([
                [], // Empty batch
                [], // Another empty batch
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            expect(result).toBeNull()
        })

        it('should preserve order of results from sub-pipeline', async () => {
            const subPipeline = new MockBatchProcessingPipeline([
                [createContext(ok('first'), context1)],
                [createContext(ok('second'), context2)],
                [createContext(ok('third'), context3)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('first'), context1),
                createContext(ok('second'), context2),
                createContext(ok('third'), context3),
            ])
        })

        it('should handle large number of batches', async () => {
            const batches: BatchPipelineResultWithContext<string, any>[] = []
            for (let i = 0; i < 10; i++) {
                batches.push([createContext(ok(`item${i}`), context1)])
            }

            const subPipeline = new MockBatchProcessingPipeline(batches)
            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toHaveLength(10)
            expect(result![0]).toEqual(createContext(ok('item0'), context1))
            expect(result![9]).toEqual(createContext(ok('item9'), context1))
            expect(result2).toBeNull()
        })

        it('should resume after returning null when more batches are fed', async () => {
            const subPipeline = new MockBatchProcessingPipeline([
                [createContext(ok('first'), context1)],
                [createContext(ok('second'), context2)],
            ])

            const gatherPipeline = new GatheringBatchPipeline(subPipeline)

            // First round: process initial batches
            const result1 = await gatherPipeline.next()
            expect(result1).toEqual([createContext(ok('first'), context1), createContext(ok('second'), context2)])

            // Should return null when exhausted
            const result2 = await gatherPipeline.next()
            expect(result2).toBeNull()

            // Feed more batches
            subPipeline.feed([createContext(ok('third'), context3)])

            // Should resume processing
            const result3 = await gatherPipeline.next()
            expect(result3).toEqual([createContext(ok('third'), context3)])

            // Should return null again
            const result4 = await gatherPipeline.next()
            expect(result4).toBeNull()
        })
    })
})
