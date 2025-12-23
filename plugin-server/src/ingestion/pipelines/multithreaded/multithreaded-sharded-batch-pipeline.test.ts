import * as path from 'path'

import { parseJSON } from '../../../utils/json-parse'
import { BatchPipeline, BatchPipelineResultWithContext } from '../batch-pipeline.interface'
import { PipelineContext, PipelineResultWithContext } from '../pipeline.interface'
import { PipelineResultType, ok } from '../results'
import { MultithreadedShardedBatchPipeline } from './multithreaded-sharded-batch-pipeline'
import { Serializable } from './serializable'

interface TestInput {
    id: number
    groupKey: string
}

interface TestOutput {
    processed: true
    original: TestInput
}

class TestSerializable implements Serializable {
    constructor(private input: TestInput) {}

    serialize(): Uint8Array {
        return new TextEncoder().encode(JSON.stringify(this.input))
    }
}

/**
 * Simple identity batch pipeline for testing - passes through inputs unchanged.
 */
class IdentityBatchPipeline implements BatchPipeline<TestInput, TestInput, TestContext, TestContext> {
    private buffer: PipelineResultWithContext<TestInput, TestContext>[] = []

    feed(elements: BatchPipelineResultWithContext<TestInput, TestContext>): void {
        this.buffer.push(...elements)
    }

    next(): Promise<BatchPipelineResultWithContext<TestInput, TestContext> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const batch = this.buffer.splice(0, this.buffer.length)
        return Promise.resolve(batch)
    }
}

interface TestContext {
    originalId: number
}

function createTestContext(id: number): PipelineContext<TestContext> {
    return {
        originalId: id,
        sideEffects: [],
        warnings: [],
    }
}

describe('MultithreadedShardedBatchPipeline', () => {
    const testPipelineWorkerPath = path.join(__dirname, 'test-pipeline-worker.ts')

    describe('basic processing', () => {
        it('should process events through workers and return results', async () => {
            const previousPipeline = new IdentityBatchPipeline()

            const pipeline = new MultithreadedShardedBatchPipeline<
                TestInput,
                TestInput,
                TestOutput,
                string,
                TestContext,
                TestContext
            >((input) => input.groupKey, previousPipeline, {
                numWorkers: 2,
                workerPath: testPipelineWorkerPath,
                workerConfig: {},
                serializer: (input) => new TestSerializable(input),
                deserializer: (data) => {
                    const parsed = parseJSON(new TextDecoder().decode(data))
                    return parsed as TestOutput
                },
            })

            try {
                // Feed events
                previousPipeline.feed([
                    { result: ok({ id: 1, groupKey: 'group-a' }), context: createTestContext(1) },
                    { result: ok({ id: 2, groupKey: 'group-b' }), context: createTestContext(2) },
                ])

                // Collect results
                const results: PipelineResultWithContext<TestOutput, TestContext>[] = []
                let batch
                while ((batch = await pipeline.next()) !== null) {
                    results.push(...batch)
                }

                expect(results).toHaveLength(2)
                expect(results.every((r) => r.result.type === PipelineResultType.OK)).toBe(true)

                const okResults = results.filter((r) => r.result.type === PipelineResultType.OK)
                expect(okResults.map((r) => (r.result as any).value.processed)).toEqual([true, true])
            } finally {
                await pipeline.shutdown()
            }
        })

        it('should preserve context through processing', async () => {
            const previousPipeline = new IdentityBatchPipeline()

            const pipeline = new MultithreadedShardedBatchPipeline<
                TestInput,
                TestInput,
                TestOutput,
                string,
                TestContext,
                TestContext
            >((input) => input.groupKey, previousPipeline, {
                numWorkers: 1,
                workerPath: testPipelineWorkerPath,
                workerConfig: {},
                serializer: (input) => new TestSerializable(input),
                deserializer: (data) => parseJSON(new TextDecoder().decode(data)) as TestOutput,
            })

            try {
                previousPipeline.feed([{ result: ok({ id: 42, groupKey: 'test' }), context: createTestContext(42) }])

                const results: PipelineResultWithContext<TestOutput, TestContext>[] = []
                let batch
                while ((batch = await pipeline.next()) !== null) {
                    results.push(...batch)
                }

                expect(results).toHaveLength(1)
                expect(results[0].context.originalId).toBe(42)
            } finally {
                await pipeline.shutdown()
            }
        })
    })

    describe('sharding', () => {
        it('should route events with same group key to same worker', async () => {
            const previousPipeline = new IdentityBatchPipeline()

            const pipeline = new MultithreadedShardedBatchPipeline<
                TestInput,
                TestInput,
                TestOutput,
                string,
                TestContext,
                TestContext
            >((input) => input.groupKey, previousPipeline, {
                numWorkers: 4,
                workerPath: testPipelineWorkerPath,
                workerConfig: {},
                serializer: (input) => new TestSerializable(input),
                deserializer: (data) => parseJSON(new TextDecoder().decode(data)) as TestOutput,
            })

            try {
                // All events have same group key
                previousPipeline.feed([
                    { result: ok({ id: 1, groupKey: 'same-key' }), context: createTestContext(1) },
                    { result: ok({ id: 2, groupKey: 'same-key' }), context: createTestContext(2) },
                    { result: ok({ id: 3, groupKey: 'same-key' }), context: createTestContext(3) },
                ])

                const results: PipelineResultWithContext<TestOutput, TestContext>[] = []
                let batch
                while ((batch = await pipeline.next()) !== null) {
                    results.push(...batch)
                }

                expect(results).toHaveLength(3)
                expect(results.every((r) => r.result.type === PipelineResultType.OK)).toBe(true)
            } finally {
                await pipeline.shutdown()
            }
        })

        it('should distribute events with different keys across workers', async () => {
            const previousPipeline = new IdentityBatchPipeline()

            const pipeline = new MultithreadedShardedBatchPipeline<
                TestInput,
                TestInput,
                TestOutput,
                string,
                TestContext,
                TestContext
            >((input) => input.groupKey, previousPipeline, {
                numWorkers: 4,
                workerPath: testPipelineWorkerPath,
                workerConfig: {},
                serializer: (input) => new TestSerializable(input),
                deserializer: (data) => parseJSON(new TextDecoder().decode(data)) as TestOutput,
            })

            try {
                // Events with different group keys
                previousPipeline.feed([
                    { result: ok({ id: 1, groupKey: 'key-a' }), context: createTestContext(1) },
                    { result: ok({ id: 2, groupKey: 'key-b' }), context: createTestContext(2) },
                    { result: ok({ id: 3, groupKey: 'key-c' }), context: createTestContext(3) },
                    { result: ok({ id: 4, groupKey: 'key-d' }), context: createTestContext(4) },
                ])

                const results: PipelineResultWithContext<TestOutput, TestContext>[] = []
                let batch
                while ((batch = await pipeline.next()) !== null) {
                    results.push(...batch)
                }

                expect(results).toHaveLength(4)
                expect(results.every((r) => r.result.type === PipelineResultType.OK)).toBe(true)
            } finally {
                await pipeline.shutdown()
            }
        })
    })

    describe('flush', () => {
        it('should wait for all pending work to complete', async () => {
            const previousPipeline = new IdentityBatchPipeline()

            const pipeline = new MultithreadedShardedBatchPipeline<
                TestInput,
                TestInput,
                TestOutput,
                string,
                TestContext,
                TestContext
            >((input) => input.groupKey, previousPipeline, {
                numWorkers: 2,
                workerPath: testPipelineWorkerPath,
                workerConfig: {},
                serializer: (input) => new TestSerializable(input),
            })

            try {
                previousPipeline.feed([
                    { result: ok({ id: 1, groupKey: 'a' }), context: createTestContext(1) },
                    { result: ok({ id: 2, groupKey: 'b' }), context: createTestContext(2) },
                ])

                // Start processing
                await pipeline.next()

                // Flush should complete without error
                await expect(pipeline.flush()).resolves.toBeUndefined()
            } finally {
                await pipeline.shutdown()
            }
        })
    })
})
