import { Message } from 'node-rdkafka'

import { createContext, createNewBatchPipeline } from './helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { dlq, drop, isOkResult, ok, redirect } from './results'
import { ShardingBatchPipeline } from './sharding-batch-pipeline'

describe('ShardingBatchPipeline', () => {
    let message1: Message
    let message2: Message
    let message3: Message
    let message4: Message
    let context1: { message: Message }
    let context2: { message: Message }
    let context3: { message: Message }
    let context4: { message: Message }

    beforeEach(() => {
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

        message4 = {
            topic: 'test-topic',
            partition: 0,
            offset: 4,
            key: Buffer.from('key4'),
            value: Buffer.from('value4'),
            timestamp: Date.now() + 3,
        } as Message

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
        context4 = { message: message4 }
    })

    describe('constructor', () => {
        it('should create instance with sharding function and shard pipelines', () => {
            const shardingFn = () => 0
            const shardPipelines = [createNewBatchPipeline<string>().build(), createNewBatchPipeline<string>().build()]
            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ShardingBatchPipeline(shardingFn, shardPipelines, previousPipeline)

            expect(pipeline).toBeInstanceOf(ShardingBatchPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to previous pipeline', () => {
            const shardingFn = () => 0
            const shardPipelines = [createNewBatchPipeline<string>().build()]
            const previousPipeline = createNewBatchPipeline<string>().build()
            const spy = jest.spyOn(previousPipeline, 'feed')

            const pipeline = new ShardingBatchPipeline(shardingFn, shardPipelines, previousPipeline)
            const testBatch = [createContext(ok('test'), context1)]

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const shardingFn = () => 0
            const shardPipelines = [createNewBatchPipeline<string>().build()]
            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ShardingBatchPipeline(shardingFn, shardPipelines, previousPipeline)

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should route messages to correct shard based on hash', async () => {
            const shardingFn = jest.fn((resultWithContext: PipelineResultWithContext<string, any>) => {
                const value = (resultWithContext.result as any).value as string
                return value === 'shard0' ? 0 : 1
            })

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toUpperCase())))
                .build()
            const shard1Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toLowerCase())))
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [createContext(ok('shard0'), context1), createContext(ok('shard1'), context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            const results: PipelineResultWithContext<string, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(shardingFn).toHaveBeenCalledTimes(2)
            expect(results).toHaveLength(2)
            expect(results.find((r) => isOkResult(r.result) && r.result.value === 'SHARD0')).toBeDefined()
            expect(results.find((r) => isOkResult(r.result) && r.result.value === 'shard1')).toBeDefined()
        })

        it('should handle modulo sharding correctly', async () => {
            const shardingFn = (resultWithContext: PipelineResultWithContext<string, any>) => {
                const value = parseInt((resultWithContext.result as any).value as string)
                return value
            }

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(`s0-${v}`)))
                .build()
            const shard1Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(`s1-${v}`)))
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('0'), context1),
                createContext(ok('1'), context2),
                createContext(ok('2'), context3),
                createContext(ok('3'), context4),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            const results: PipelineResultWithContext<string, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(4)
            expect(
                results.filter((r) => isOkResult(r.result) && (r.result.value === 's0-0' || r.result.value === 's0-2'))
            ).toHaveLength(2)
            expect(
                results.filter((r) => isOkResult(r.result) && (r.result.value === 's1-1' || r.result.value === 's1-3'))
            ).toHaveLength(2)
        })

        it('should work with builder pattern', async () => {
            const pipeline = createNewBatchPipeline<string>()
                .sharding(
                    (resultWithContext: PipelineResultWithContext<string, any>) =>
                        parseInt((resultWithContext.result as any).value as string),
                    2,
                    (builder) => builder.pipeBatch(async (values) => values.map((v) => ok(v.toUpperCase())))
                )
                .build()

            const testBatch = [
                createContext(ok('0'), context1),
                createContext(ok('1'), context2),
                createContext(ok('2'), context3),
            ]
            pipeline.feed(testBatch)

            const results: PipelineResultWithContext<string, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(3)
            expect(results.every((r) => isOkResult(r.result) && r.result.value === r.result.value.toUpperCase())).toBe(
                true
            )
        })

        it('should process multiple shards concurrently', async () => {
            const processingOrder: string[] = []

            const createDelayedShard = (shardId: number, delay: number) => {
                return createNewBatchPipeline<string>()
                    .pipeBatch(async (values) => {
                        processingOrder.push(`start-shard${shardId}`)
                        await new Promise((resolve) => setTimeout(resolve, delay))
                        processingOrder.push(`end-shard${shardId}`)
                        return values.map((v) => ok(`${v}-shard${shardId}`))
                    })
                    .build()
            }

            const shardingFn = (resultWithContext: PipelineResultWithContext<string, any>) => {
                return parseInt((resultWithContext.result as any).value as string)
            }

            const shard0Pipeline = createDelayedShard(0, 50)
            const shard1Pipeline = createDelayedShard(1, 10)

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [createContext(ok('0'), context1), createContext(ok('1'), context2)]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            const result1 = await pipeline.next()
            const result2 = await pipeline.next()

            expect(result1).toHaveLength(1)
            expect(result2).toHaveLength(1)

            const allResults = [...result1!, ...result2!]
            expect(allResults.filter((r) => isOkResult(r.result) && r.result.value === '1-shard1')).toHaveLength(1)
            expect(allResults.filter((r) => isOkResult(r.result) && r.result.value === '0-shard0')).toHaveLength(1)

            expect(processingOrder).toEqual(['start-shard0', 'start-shard1', 'end-shard1', 'end-shard0'])
        })

        it('should handle multiple batches from previous pipeline', async () => {
            const shardingFn = (resultWithContext: PipelineResultWithContext<string, any>) =>
                parseInt((resultWithContext.result as any).value as string) % 2

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(`s0-${v}`)))
                .build()
            const shard1Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(`s1-${v}`)))
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            // Feed first batch
            previousPipeline.feed([createContext(ok('0'), context1), createContext(ok('1'), context2)])
            const result1 = await pipeline.next()
            const result2 = await pipeline.next()

            // Feed second batch
            previousPipeline.feed([createContext(ok('2'), context3), createContext(ok('3'), context4)])
            const result3 = await pipeline.next()
            const result4 = await pipeline.next()

            const allResults = [...(result1 || []), ...(result2 || []), ...(result3 || []), ...(result4 || [])]
            expect(allResults).toHaveLength(4)
            expect(allResults.map((r) => (isOkResult(r.result) ? r.result.value : null)).sort()).toEqual([
                's0-0',
                's0-2',
                's1-1',
                's1-3',
            ])
        })

        it('should handle all messages going to same shard', async () => {
            const shardingFn = () => 0

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toUpperCase())))
                .build()
            const shard1Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toLowerCase())))
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('hello'), context1),
                createContext(ok('world'), context2),
                createContext(ok('test'), context3),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            const result = await pipeline.next()

            expect(result).toHaveLength(3)
            expect(result!.every((r) => isOkResult(r.result) && r.result.value === r.result.value.toUpperCase())).toBe(
                true
            )

            const result2 = await pipeline.next()
            expect(result2).toBeNull()
        })

        it('should handle non-success results (drop, dlq, redirect)', async () => {
            const shardingFn = jest.fn(() => 0)

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toUpperCase())))
                .build()

            const dropResult = drop<string>('test drop')
            const dlqResult = dlq<string>('test dlq', new Error('test error'))
            const redirectResult = redirect<string>('test redirect', 'test-topic')

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('hello'), context1),
                createContext(dropResult, context2),
                createContext(dlqResult, context3),
                createContext(redirectResult, context4),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline], previousPipeline)

            // First call returns non-ok results immediately
            const result1 = await pipeline.next()
            expect(result1).toHaveLength(3)
            expect(result1![0].result).toEqual(dropResult)
            expect(result1![1].result).toEqual(dlqResult)
            expect(result1![2].result).toEqual(redirectResult)

            // Sharding function should only be called for ok results
            expect(shardingFn).toHaveBeenCalledTimes(1)

            // Second call returns ok result from shard
            const result2 = await pipeline.next()
            expect(result2).toHaveLength(1)
            expect(result2![0].result).toEqual(expect.objectContaining({ type: 0, value: 'HELLO' }))
        })

        it('should handle empty batches', async () => {
            const shardingFn = () => 0
            const shard0Pipeline = createNewBatchPipeline<string>().build()
            const previousPipeline = createNewBatchPipeline<string>().build()

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline], previousPipeline)

            previousPipeline.feed([])
            const result = await pipeline.next()

            expect(result).toBeNull()
        })

        it('should handle single shard', async () => {
            const shardingFn = () => 0

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => values.map((v) => ok(v.toUpperCase())))
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [createContext(ok('test'), context1)]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline], previousPipeline)

            const result = await pipeline.next()

            expect(result).toHaveLength(1)
            expect(isOkResult(result![0].result) && result![0].result.value).toBe('TEST')
        })

        it('should handle many shards', async () => {
            const numShards = 5
            const shardingFn = (resultWithContext: PipelineResultWithContext<string, any>) =>
                parseInt((resultWithContext.result as any).value as string)

            const shardPipelines = Array.from({ length: numShards }, (_, i) =>
                createNewBatchPipeline<string>()
                    .pipeBatch(async (values) => values.map((v) => ok(`s${i}-${v}`)))
                    .build()
            )

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = Array.from({ length: 10 }, (_, i) => createContext(ok(String(i)), context1))
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, shardPipelines, previousPipeline)

            const results: PipelineResultWithContext<string, any>[] = []
            let result = await pipeline.next()
            while (result !== null) {
                results.push(...result)
                result = await pipeline.next()
            }

            expect(results).toHaveLength(10)
            // Verify each number got routed to correct shard
            for (let i = 0; i < 10; i++) {
                const expectedShard = i % numShards
                expect(
                    results.find((r) => isOkResult(r.result) && r.result.value === `s${expectedShard}-${i}`)
                ).toBeDefined()
            }
        })

        it('should preserve order within each shard', async () => {
            const shardingFn = (resultWithContext: PipelineResultWithContext<string, any>) =>
                parseInt((resultWithContext.result as any).value as string) % 2

            const shard0Results: string[] = []
            const shard1Results: string[] = []

            const shard0Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => {
                    shard0Results.push(...values)
                    return values.map((v) => ok(v))
                })
                .build()

            const shard1Pipeline = createNewBatchPipeline<string>()
                .pipeBatch(async (values) => {
                    shard1Results.push(...values)
                    return values.map((v) => ok(v))
                })
                .build()

            const previousPipeline = createNewBatchPipeline<string>().build()
            const testBatch = [
                createContext(ok('0'), context1),
                createContext(ok('2'), context2),
                createContext(ok('4'), context3),
                createContext(ok('1'), context4),
            ]
            previousPipeline.feed(testBatch)

            const pipeline = new ShardingBatchPipeline(shardingFn, [shard0Pipeline, shard1Pipeline], previousPipeline)

            await pipeline.next()
            await pipeline.next()

            // Messages should maintain order within their shard
            expect(shard0Results).toEqual(['0', '2', '4'])
            expect(shard1Results).toEqual(['1'])
        })
    })
})
