import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { ConcurrentlyGroupingBatchPipeline } from './concurrently-grouping-batch-pipeline'
import { createContext, createNewBatchPipeline, createNewPipeline } from './helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { dlq, drop, ok, redirect } from './results'

// xoshiro128** PRNG (Vigna & Blackman, 2018) - fast 128-bit state generator
function xoshiro128ss(a: number, b: number, c: number, d: number): () => number {
    return function () {
        const t = b << 9
        let r = b * 5
        r = ((r << 7) | (r >>> 25)) * 9
        c ^= a
        d ^= b
        b ^= c
        a ^= d
        c ^= t
        d = (d << 11) | (d >>> 21)
        return (r >>> 0) / 4294967296
    }
}

describe('ConcurrentlyGroupingBatchPipeline', () => {
    let message1: Message
    let message2: Message
    let message3: Message
    let message4: Message
    let context1: { message: Message }
    let context2: { message: Message }
    let context3: { message: Message }
    let context4: { message: Message }

    beforeEach(() => {
        jest.useFakeTimers()

        message1 = createTestMessage({ offset: 1, key: Buffer.from('key1'), value: Buffer.from('value1') })
        message2 = createTestMessage({ offset: 2, key: Buffer.from('key2'), value: Buffer.from('value2') })
        message3 = createTestMessage({ offset: 3, key: Buffer.from('key3'), value: Buffer.from('value3') })
        message4 = createTestMessage({ offset: 4, key: Buffer.from('key4'), value: Buffer.from('value4') })

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
        context4 = { message: message4 }
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('constructor', () => {
        it('should create instance with grouping function, processor, and previous pipeline', () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok({ ...input, processed: true }))
            )
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            expect(pipeline).toBeInstanceOf(ConcurrentlyGroupingBatchPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to previous pipeline', () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok(input))
            )
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const spy = jest.spyOn(previousPipeline, 'feed')

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)
            const testBatch = [createContext(ok({ value: 'test', group: 'A' }), context1)]

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok(input))
            )
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should rethrow processor errors', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((_input) => {
                return Promise.reject(new Error('Processor error'))
            })

            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const testBatch = [createContext(ok({ value: 'test', group: 'A' }), context1)]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            await expect(pipeline.next()).rejects.toThrow('Processor error')
        })
    })

    describe('grouping and sequential processing', () => {
        it('should group items by key and process each group', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok({ ...input, processed: true }))
            )
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
                createContext(ok({ value: 'a2', group: 'A' }), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const results: PipelineResultWithContext<any, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.result.type === 0 && (r.result as any).value.processed)).toBe(true)
        })

        it('should process items within each group sequentially', async () => {
            const processingOrder: string[] = []
            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                processingOrder.push(`start-${input.value}`)
                await new Promise((resolve) => setTimeout(resolve, 10))
                processingOrder.push(`end-${input.value}`)
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'a2', group: 'A' }), context2),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const resultsPromise = (async () => {
                let result = await pipeline.next()
                while (result !== null) {
                    result = await pipeline.next()
                }
            })()

            await jest.advanceTimersByTimeAsync(100)
            await resultsPromise

            // Within group A, items should be processed sequentially (a1 completes before a2 starts)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2', 'end-a2'])
        })

        it('should return results as groups complete (order not guaranteed)', async () => {
            // Fixed seeds for deterministic test runs
            const random = xoshiro128ss(0x9e3779b9, 0x243f6a88, 0xb7e15162, 0x6c078965)

            const groupCount = 50
            const totalElements = 500
            const groupNextIndex = new Map<string, number>()

            // Generate elements by randomly picking a group and assigning sequential indices
            const events: { group: string; groupIndex: number }[] = []
            for (let i = 0; i < totalElements; i++) {
                const group = `group-${Math.floor(random() * groupCount)}`
                const groupIndex = groupNextIndex.get(group) ?? 0
                events.push({ group, groupIndex })
                groupNextIndex.set(group, groupIndex + 1)
            }

            const processor = createNewPipeline<{ group: string; groupIndex: number }>().pipe((input) =>
                Promise.resolve(ok({ ...input, processed: true }))
            )
            const previousPipeline = createNewBatchPipeline<{ group: string; groupIndex: number }>().build()

            const testBatch = events.map((e) => createContext(ok(e), context1))
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Collect results and track per-group ordering
            const groupResults = new Map<string, number[]>()
            let result = await pipeline.next()
            while (result !== null) {
                for (const r of result) {
                    const { group, groupIndex } = (r.result as any).value
                    if (!groupResults.has(group)) {
                        groupResults.set(group, [])
                    }
                    groupResults.get(group)!.push(groupIndex)
                }
                result = await pipeline.next()
            }

            // Assert all groups with elements were returned
            expect(groupResults.size).toBe(groupNextIndex.size)

            // Assert each group has correct ordering and all elements
            for (const [group, indices] of groupResults) {
                const expectedCount = groupNextIndex.get(group)!

                // Check indices are in ascending order (sequential processing within group)
                for (let i = 1; i < indices.length; i++) {
                    expect(indices[i]).toBeGreaterThan(indices[i - 1])
                }

                // Check all indices are present (0 to expectedCount-1)
                expect(indices).toHaveLength(expectedCount)
                expect(indices).toEqual([...Array(expectedCount).keys()])
            }
        })
    })

    describe('concurrent group processing', () => {
        it('should process different groups concurrently', async () => {
            const groupCount = 1000
            const resolvers: (() => void)[] = []
            const startedPromises: Promise<void>[] = []
            for (let i = 0; i < groupCount; i++) {
                startedPromises.push(new Promise<void>((resolve) => resolvers.push(resolve)))
            }

            const processor = createNewPipeline<{ index: number; group: string }>().pipe(async (input) => {
                // Signal that this group has started
                resolvers[input.index]()
                // Wait for all groups to start - if processing were sequential, this would deadlock
                await Promise.all(startedPromises)
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ index: number; group: string }>().build()

            const testBatch = []
            for (let i = 0; i < groupCount; i++) {
                testBatch.push(createContext(ok({ index: i, group: `group-${i}` }), context1))
            }
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const results: PipelineResultWithContext<any, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(groupCount)
            const indices = results.map((r) => (r.result as any).value.index).sort((a, b) => a - b)
            expect(indices).toEqual([...Array(groupCount).keys()])
        })

        it('should not block other groups when one group is slow', async () => {
            const normalGroupCount = 100
            const elementsPerGroup = 100
            const slowGroupDelay = 10000

            const processor = createNewPipeline<{ index: number; group: string }>().pipe(async (input) => {
                if (input.group === 'slow') {
                    await new Promise((resolve) => setTimeout(resolve, slowGroupDelay))
                }
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ index: number; group: string }>().build()

            const testBatch = []
            let index = 0
            for (let g = 0; g < normalGroupCount; g++) {
                for (let e = 0; e < elementsPerGroup; e++) {
                    testBatch.push(createContext(ok({ index: index++, group: `group-${g}` }), context1))
                }
            }
            testBatch.push(createContext(ok({ index: index++, group: 'slow' }), context1))
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Consume results until we have all normal groups
            const results: PipelineResultWithContext<any, any>[] = []
            while (results.length < normalGroupCount * elementsPerGroup) {
                const result = await pipeline.next()
                if (result !== null) {
                    results.push(...result)
                }
            }

            // All normal groups should be processed, slow group should not be included yet
            expect(results).toHaveLength(normalGroupCount * elementsPerGroup)
            expect(results.every((r) => (r.result as any).value.group !== 'slow')).toBe(true)

            // Advance time for the slow group to complete
            await jest.advanceTimersByTimeAsync(slowGroupDelay)
            const slowResult = await pipeline.next()

            // Now we should have the slow group result
            expect(slowResult).toHaveLength(1)
            expect((slowResult![0].result as any).value.group).toBe('slow')
        })
    })

    describe('non-success results', () => {
        it('should preserve non-success results without processing', async () => {
            let processorCallCount = 0
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) => {
                processorCallCount++
                return Promise.resolve(ok(input))
            })
            const dropResult = drop<{ value: string; group: string }>('test drop')
            const dlqResult = dlq<{ value: string; group: string }>('test dlq', new Error('test error'))
            const redirectResult = redirect<{ value: string; group: string }>('test redirect', 'test-topic')

            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const testBatch: BatchPipelineResultWithContext<{ value: string; group: string }, any> = [
                createContext(dropResult, context1),
                createContext(dlqResult, context2),
                createContext(redirectResult, context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const results: PipelineResultWithContext<any, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(processorCallCount).toBe(0)
            expect(results).toHaveLength(3)
            expect(results.map((r) => r.result)).toEqual(
                expect.arrayContaining([dropResult, dlqResult, redirectResult])
            )
        })

        it('should handle mixed success and non-success results', async () => {
            let processorCallCount = 0
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) => {
                processorCallCount++
                return Promise.resolve(ok({ ...input, processed: true }))
            })
            const dropResult = drop<{ value: string; group: string }>('test drop')

            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const testBatch: BatchPipelineResultWithContext<{ value: string; group: string }, any> = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(dropResult, context2),
                createContext(ok({ value: 'a2', group: 'A' }), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            const results: PipelineResultWithContext<any, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(processorCallCount).toBe(2)
            expect(results).toHaveLength(3)
            const okResults = results.filter((r) => r.result.type === 0)
            expect(okResults).toHaveLength(2)
            expect(okResults.every((r) => (r.result as any).value.processed)).toBe(true)
        })
    })

    describe('groupBy builder DSL', () => {
        it('should work with the groupBy builder method', async () => {
            const pipeline = createNewBatchPipeline<{ value: string; group: string }>()
                .groupBy((input) => input.group)
                .concurrently((group) =>
                    group.sequentially((builder) =>
                        builder.pipe((input) => Promise.resolve(ok({ ...input, processed: true })))
                    )
                )
                .build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
                createContext(ok({ value: 'a2', group: 'A' }), context3),
            ]
            pipeline.feed(testBatch)

            const results: PipelineResultWithContext<any, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.result.type === 0 && (r.result as any).value.processed)).toBe(true)
        })

        it('should chain with gather to collect all results', async () => {
            const pipeline = createNewBatchPipeline<{ value: string; group: string }>()
                .groupBy((input) => input.group)
                .concurrently((group) =>
                    group.sequentially((builder) =>
                        builder.pipe((input) => Promise.resolve(ok({ ...input, processed: true })))
                    )
                )
                .gather()
                .build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
                createContext(ok({ value: 'a2', group: 'A' }), context3),
            ]
            pipeline.feed(testBatch)

            const result = await pipeline.next()

            expect(result).not.toBeNull()
            expect(result).toHaveLength(3)
        })
    })

    describe('ordering across next() calls', () => {
        it('should maintain ordering when new items arrive for a group that is still processing', async () => {
            const processingOrder: string[] = []
            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                processingOrder.push(`start-${input.value}`)
                await new Promise((resolve) => setTimeout(resolve, 50))
                processingOrder.push(`end-${input.value}`)
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Feed first batch with items for group A
            previousPipeline.feed([
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'a2', group: 'A' }), context2),
            ])
            expect(processingOrder).toEqual([])

            // Start processing
            const nextPromise = pipeline.next()
            expect(processingOrder).toEqual([])

            // Advance past microtasks - a1 should start processing
            await jest.advanceTimersByTimeAsync(0)
            expect(processingOrder).toEqual(['start-a1'])

            // Feed more items for group A while a1 is still processing
            previousPipeline.feed([createContext(ok({ value: 'a3', group: 'A' }), context3)])
            expect(processingOrder).toEqual(['start-a1'])

            // Advance to complete a1 (50ms), a2 should start
            await jest.advanceTimersByTimeAsync(50)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2'])

            // Advance to complete a2 - first batch processing ends
            await jest.advanceTimersByTimeAsync(50)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2', 'end-a2'])

            // Await first next() - gets results for a1 and a2
            const results: any[] = []
            const result1 = await nextPromise
            if (result1) {
                results.push(...result1)
            }
            expect(results).toHaveLength(2)

            // Call next() to route and process a3
            const nextPromise2 = pipeline.next()
            await jest.advanceTimersByTimeAsync(0)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2', 'end-a2', 'start-a3'])

            // Advance to complete a3
            await jest.advanceTimersByTimeAsync(50)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2', 'end-a2', 'start-a3', 'end-a3'])

            const result2 = await nextPromise2
            if (result2) {
                results.push(...result2)
            }
            expect(results).toHaveLength(3)
        })

        it('should not block other groups from starting when one group has queued items', async () => {
            const processingOrder: string[] = []
            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                processingOrder.push(`start-${input.value}`)
                // B is slow (1000ms), others are fast (50ms)
                const delay = input.group === 'B' ? 1000 : 50
                await new Promise((resolve) => setTimeout(resolve, delay))
                processingOrder.push(`end-${input.value}`)
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()
            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Feed one element each for groups A and B (B is slow)
            previousPipeline.feed([
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
            ])
            expect(processingOrder).toEqual([])

            // Start processing - both start concurrently
            const nextPromise = pipeline.next()
            await jest.advanceTimersByTimeAsync(0)
            expect(processingOrder).toEqual(['start-a1', 'start-b1'])

            // Advance 50ms - A completes, B still processing
            await jest.advanceTimersByTimeAsync(50)
            expect(processingOrder).toEqual(['start-a1', 'start-b1', 'end-a1'])

            // Feed one element each for groups B and C
            // b2 will be queued (B is still processing b1), c1 should start immediately
            previousPipeline.feed([
                createContext(ok({ value: 'b2', group: 'B' }), context3),
                createContext(ok({ value: 'c1', group: 'C' }), context4),
            ])
            expect(processingOrder).toEqual(['start-a1', 'start-b1', 'end-a1'])

            // Await first next() - returns A's result
            const results: any[] = []
            const result1 = await nextPromise
            if (result1) {
                results.push(...result1)
            }
            expect(results).toHaveLength(1)
            expect((results[0].result as any).value.value).toBe('a1')

            // Call next() to route second batch - c1 starts even though b2 is queued
            const nextPromise2 = pipeline.next()
            await jest.advanceTimersByTimeAsync(0)
            expect(processingOrder).toEqual(['start-a1', 'start-b1', 'end-a1', 'start-c1'])

            // Advance 50ms - C completes, B still processing b1
            await jest.advanceTimersByTimeAsync(50)
            expect(processingOrder).toEqual(['start-a1', 'start-b1', 'end-a1', 'start-c1', 'end-c1'])

            // Await second next() - returns C's result
            const result2 = await nextPromise2
            if (result2) {
                results.push(...result2)
            }
            expect(results).toHaveLength(2)
            expect((results[1].result as any).value.value).toBe('c1')

            // Advance remaining time for B to complete b1 (1000 - 50 - 50 = 900ms)
            const nextPromise3 = pipeline.next()
            await jest.advanceTimersByTimeAsync(900)
            expect(processingOrder).toEqual(['start-a1', 'start-b1', 'end-a1', 'start-c1', 'end-c1', 'end-b1'])

            // Await third next() - returns b1's result
            const result3 = await nextPromise3
            if (result3) {
                results.push(...result3)
            }
            expect(results).toHaveLength(3)

            // Call next() to route b2 and start processing
            const nextPromise4 = pipeline.next()
            await jest.advanceTimersByTimeAsync(0)
            expect(processingOrder).toEqual([
                'start-a1',
                'start-b1',
                'end-a1',
                'start-c1',
                'end-c1',
                'end-b1',
                'start-b2',
            ])

            // Advance 1000ms for b2 to complete
            await jest.advanceTimersByTimeAsync(1000)
            expect(processingOrder).toEqual([
                'start-a1',
                'start-b1',
                'end-a1',
                'start-c1',
                'end-c1',
                'end-b1',
                'start-b2',
                'end-b2',
            ])

            const result4 = await nextPromise4
            if (result4) {
                results.push(...result4)
            }
            expect(results).toHaveLength(4)
        })
    })

    describe('complex grouping scenarios', () => {
        it('should handle multiple items per group with sequential processing', async () => {
            const processingOrder: string[] = []
            const pipeline = createNewBatchPipeline<{ value: string; group: string }>()
                .groupBy((input) => input.group)
                .concurrently((group) =>
                    group.sequentially((builder) =>
                        builder.pipe(async (input) => {
                            processingOrder.push(`start-${input.value}`)
                            await new Promise((resolve) => setTimeout(resolve, 10))
                            processingOrder.push(`end-${input.value}`)
                            return ok({ ...input, processed: true })
                        })
                    )
                )
                .gather()
                .build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'a2', group: 'A' }), context2),
                createContext(ok({ value: 'b1', group: 'B' }), context3),
                createContext(ok({ value: 'b2', group: 'B' }), context4),
            ]
            pipeline.feed(testBatch)

            const resultPromise = pipeline.next()
            await jest.advanceTimersByTimeAsync(100)
            await resultPromise

            // Verify sequential processing within groups
            const a1Start = processingOrder.indexOf('start-a1')
            const a1End = processingOrder.indexOf('end-a1')
            const a2Start = processingOrder.indexOf('start-a2')

            const b1Start = processingOrder.indexOf('start-b1')
            const b1End = processingOrder.indexOf('end-b1')
            const b2Start = processingOrder.indexOf('start-b2')

            // Within group A: a1 ends before a2 starts
            expect(a1End).toBeLessThan(a2Start)

            // Within group B: b1 ends before b2 starts
            expect(b1End).toBeLessThan(b2Start)

            // Groups are concurrent: both start before either fully completes all items
            expect(a1Start).toBeLessThan(b1End + 1 || b2Start)
            expect(b1Start).toBeLessThan(a1End + 1 || a2Start)
        })

        it('should handle empty batches gracefully', async () => {
            const pipeline = createNewBatchPipeline<{ value: string; group: string }>()
                .groupBy((input) => input.group)
                .concurrently((group) =>
                    group.sequentially((builder) =>
                        builder.pipe((input) => Promise.resolve(ok({ ...input, processed: true })))
                    )
                )
                .build()

            pipeline.feed([])

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should handle single item groups', async () => {
            const pipeline = createNewBatchPipeline<{ value: string; group: string }>()
                .groupBy((input) => input.group)
                .concurrently((group) =>
                    group.sequentially((builder) =>
                        builder.pipe((input) => Promise.resolve(ok({ ...input, processed: true })))
                    )
                )
                .gather()
                .build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
                createContext(ok({ value: 'c1', group: 'C' }), context3),
            ]
            pipeline.feed(testBatch)

            const result = await pipeline.next()

            expect(result).not.toBeNull()
            expect(result).toHaveLength(3)
        })
    })
})
