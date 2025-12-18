import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { ConcurrentlyGroupingBatchPipeline } from './concurrently-grouping-batch-pipeline'
import { createContext, createNewBatchPipeline, createNewPipeline } from './helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { dlq, drop, ok, redirect } from './results'

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
        message1 = createTestMessage({ offset: 1, key: Buffer.from('key1'), value: Buffer.from('value1') })
        message2 = createTestMessage({ offset: 2, key: Buffer.from('key2'), value: Buffer.from('value2') })
        message3 = createTestMessage({ offset: 3, key: Buffer.from('key3'), value: Buffer.from('value3') })
        message4 = createTestMessage({ offset: 4, key: Buffer.from('key4'), value: Buffer.from('value4') })

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
        context4 = { message: message4 }
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

            let result = await pipeline.next()
            while (result !== null) {
                result = await pipeline.next()
            }

            // Within group A, items should be processed sequentially (a1 completes before a2 starts)
            expect(processingOrder).toEqual(['start-a1', 'end-a1', 'start-a2', 'end-a2'])
        })

        it('should process different groups concurrently', async () => {
            const processingOrder: string[] = []
            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                processingOrder.push(`start-${input.value}`)
                await new Promise((resolve) => setTimeout(resolve, 20))
                processingOrder.push(`end-${input.value}`)
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            let result = await pipeline.next()
            while (result !== null) {
                result = await pipeline.next()
            }

            // Groups A and B should start concurrently (both start before either ends)
            expect(processingOrder.slice(0, 2)).toEqual(expect.arrayContaining(['start-a1', 'start-b1']))
        })

        it('should preserve non-success results without processing', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok(input))
            )
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

            expect(results).toHaveLength(3)
            expect(results.map((r) => r.result)).toEqual(
                expect.arrayContaining([dropResult, dlqResult, redirectResult])
            )
        })

        it('should handle mixed success and non-success results', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe((input) =>
                Promise.resolve(ok({ ...input, processed: true }))
            )
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

            expect(results).toHaveLength(3)
            const okResults = results.filter((r) => r.result.type === 0)
            expect(okResults).toHaveLength(2)
            expect(okResults.every((r) => (r.result as any).value.processed)).toBe(true)
        })

        it('should return results as groups complete (order not guaranteed)', async () => {
            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const testBatch = [
                createContext(ok({ value: 'a1', group: 'A' }), context1),
                createContext(ok({ value: 'b1', group: 'B' }), context2),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Collect all results - order is not guaranteed between groups
            const allGroups: string[] = []
            let result = await pipeline.next()
            while (result !== null) {
                allGroups.push((result[0].result as any).value.group)
                result = await pipeline.next()
            }

            // Both groups should be present (order not guaranteed)
            expect(allGroups).toHaveLength(2)
            expect(allGroups).toContain('A')
            expect(allGroups).toContain('B')
        })

        it('should handle processor errors gracefully', async () => {
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

            // Start processing (don't await yet)
            const firstNextPromise = pipeline.next()

            // Wait a bit for processing to start, then feed more items for group A
            await new Promise((resolve) => setTimeout(resolve, 10))
            previousPipeline.feed([createContext(ok({ value: 'a3', group: 'A' }), context3)])

            // Get all results
            const results: any[] = []
            let result = await firstNextPromise
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            // Verify all items were processed
            expect(results).toHaveLength(3)

            // Verify ordering: a1 and a2 must complete before a3 starts
            const a1End = processingOrder.indexOf('end-a1')
            const a2End = processingOrder.indexOf('end-a2')
            const a3Start = processingOrder.indexOf('start-a3')

            expect(a1End).toBeLessThan(a3Start)
            expect(a2End).toBeLessThan(a3Start)
        })

        it('should process new items for a group after current batch completes', async () => {
            const processedBatches: string[][] = []
            let currentBatch: string[] = []

            const processor = createNewPipeline<{ value: string; group: string }>().pipe(async (input) => {
                currentBatch.push(input.value)
                await new Promise((resolve) => setTimeout(resolve, 20))
                return ok({ ...input, processed: true })
            })
            const previousPipeline = createNewBatchPipeline<{ value: string; group: string }>().build()

            const pipeline = new ConcurrentlyGroupingBatchPipeline((input) => input.group, processor, previousPipeline)

            // Feed first batch
            previousPipeline.feed([createContext(ok({ value: 'a1', group: 'A' }), context1)])

            // Get first result (starts processing a1)
            const result1Promise = pipeline.next()

            // Feed second batch while first is processing
            await new Promise((resolve) => setTimeout(resolve, 5))
            previousPipeline.feed([createContext(ok({ value: 'a2', group: 'A' }), context2)])

            // Complete first batch
            const result1 = await result1Promise
            processedBatches.push([...currentBatch])
            currentBatch = []

            expect(result1).toHaveLength(1)
            expect((result1![0].result as any).value.value).toBe('a1')

            // Get second result (should process a2 now)
            const result2 = await pipeline.next()
            processedBatches.push([...currentBatch])

            expect(result2).toHaveLength(1)
            expect((result2![0].result as any).value.value).toBe('a2')

            // Verify batches were processed separately (not interleaved)
            expect(processedBatches[0]).toEqual(['a1'])
            expect(processedBatches[1]).toEqual(['a2'])
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

            await pipeline.next()

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

        it('should handle empty groups gracefully', async () => {
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
