import { BatchProcessingStep } from './base-batch-pipeline'
import { withBatchRetry } from './batch-retry'
import { newBatchPipelineBuilder } from './builders'
import { createOkContext } from './helpers'
import { drop, isDlqResult, isDropResult, isOkResult, ok } from './results'

// Suppress logger output during tests
jest.mock('../../utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

jest.mock('../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

class RetriableError extends Error {
    isRetriable = true
}

class NonRetriableError extends Error {
    isRetriable = false
}

// Helper to create a batch of test inputs
function createTestBatch<T>(values: T[]) {
    return values.map((value) => createOkContext(value, {}))
}

describe('withBatchRetry', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('processes batch successfully without retries', async () => {
        const step: BatchProcessingStep<number, string> = (values) => {
            return Promise.resolve(values.map((v) => ok(String(v * 2))))
        }

        const pipeline = newBatchPipelineBuilder<number>().pipeBatchWithRetry(step).gather().build()

        const batch = createTestBatch([1, 2, 3])
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).toHaveLength(3)
        expect(results!.map((r) => (isOkResult(r.result) ? r.result.value : null))).toEqual(['2', '4', '6'])
    })

    it('retries on retriable errors', async () => {
        let attempts = 0
        const step: BatchProcessingStep<number, string> = (values) => {
            attempts++
            if (attempts < 3) {
                throw new RetriableError('Temporary failure')
            }
            return Promise.resolve(values.map((v) => ok(String(v))))
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .pipeBatchWithRetry(step, { tries: 5, sleepMs: 100 })
            .gather()
            .build()

        const batch = createTestBatch([1])
        pipeline.feed(batch)

        const resultPromise = pipeline.next()
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries
        const results = await resultPromise

        expect(attempts).toBe(3)
        expect(results).toHaveLength(1)
        expect(isOkResult(results![0].result)).toBe(true)
    })

    it('converts non-retriable errors to DLQ results', async () => {
        const step: BatchProcessingStep<number, string> = (_values) => {
            throw new NonRetriableError('Validation failed')
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .pipeBatchWithRetry(step, { tries: 3, sleepMs: 100 })
            .gather()
            .build()

        const batch = createTestBatch([1, 2])
        pipeline.feed(batch)

        const results = await pipeline.next()

        // All inputs should be DLQ'd
        expect(results).toHaveLength(2)
        expect(isDlqResult(results![0].result)).toBe(true)
        expect(isDlqResult(results![1].result)).toBe(true)
    })

    it('rethrows after exhausting retries', async () => {
        // Use real timers for this test to avoid fake timer issues with promise rejections
        jest.useRealTimers()

        const step: BatchProcessingStep<number, string> = (_values) => {
            throw new RetriableError('Always fails')
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .pipeBatchWithRetry(step, { tries: 2, sleepMs: 1 }) // Use tiny sleep for fast test
            .gather()
            .build()

        const batch = createTestBatch([1])
        pipeline.feed(batch)

        await expect(pipeline.next()).rejects.toThrow('Always fails')
    })

    it('preserves non-OK results from previous pipeline', async () => {
        // Create a pipeline where some inputs are already failed
        const failFirst: BatchProcessingStep<number, number> = (values) => {
            return Promise.resolve(values.map((v, i) => (i === 0 ? drop('test') : ok(v))))
        }

        const doubleStep: BatchProcessingStep<number, string> = (values) => {
            return Promise.resolve(values.map((v) => ok(String(v * 2))))
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .pipeBatch(failFirst)
            .pipeBatchWithRetry(doubleStep)
            .gather()
            .build()

        const batch = createTestBatch([1, 2, 3])
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).toHaveLength(3)
        // First result should still be dropped
        expect(isDropResult(results![0].result)).toBe(true)
        // Other results should be processed
        expect(isOkResult(results![1].result) && results![1].result.value).toBe('4')
        expect(isOkResult(results![2].result) && results![2].result.value).toBe('6')
    })

    // Declare steps outside it.each to preserve inferred names from variable assignment
    const myNamedStep: BatchProcessingStep<number, string> = function myNamedStep(values) {
        return Promise.resolve(values.map((v) => ok(String(v))))
    }
    const myArrowStep: BatchProcessingStep<number, string> = (values) => {
        return Promise.resolve(values.map((v) => ok(String(v))))
    }

    it.each([
        { description: 'named function expression', step: myNamedStep, expectedName: 'myNamedStep' },
        { description: 'arrow function assigned to variable', step: myArrowStep, expectedName: 'myArrowStep' },
    ])('preserves step name for $description', ({ step, expectedName }) => {
        const wrapped = withBatchRetry(step)
        expect(wrapped.name).toBe(expectedName)
    })

    describe('splitOnTimeout', () => {
        class TimeoutError extends Error {
            isRetriable = true
            constructor() {
                super('The operation was aborted due to timeout')
                this.name = 'TimeoutError'
            }
        }

        it('binary splits on timeout to isolate the poison pill and DLQ it', async () => {
            jest.useRealTimers()

            // The step fails with a timeout whenever 'poison' is in the batch
            const step: BatchProcessingStep<string, string> = (values) => {
                if (values.includes('poison')) {
                    throw new TimeoutError()
                }
                return Promise.resolve(values.map((v) => ok(`processed:${v}`)))
            }

            const wrapped = withBatchRetry(step, { tries: 1, sleepMs: 1, splitOnTimeout: true })
            const results = await wrapped(['good-1', 'good-2', 'poison', 'good-3'])

            expect(results).toHaveLength(4)
            expect(isOkResult(results[0]) && results[0].value).toBe('processed:good-1')
            expect(isOkResult(results[1]) && results[1].value).toBe('processed:good-2')
            expect(isDlqResult(results[2])).toBe(true)
            expect(isOkResult(results[3]) && results[3].value).toBe('processed:good-3')
        })

        it('does not split on non-timeout retriable errors', async () => {
            jest.useRealTimers()

            const step: BatchProcessingStep<string, string> = () => {
                throw new RetriableError('Server error')
            }

            const wrapped = withBatchRetry(step, { tries: 1, sleepMs: 1, splitOnTimeout: true })
            await expect(wrapped(['a', 'b'])).rejects.toThrow('Server error')
        })

        it('does not split single-event batches', async () => {
            jest.useRealTimers()

            const step: BatchProcessingStep<string, string> = () => {
                throw new TimeoutError()
            }

            const wrapped = withBatchRetry(step, { tries: 1, sleepMs: 1, splitOnTimeout: true })
            await expect(wrapped(['single'])).rejects.toThrow()
        })

        it('DLQs multiple poison pills in the same batch', async () => {
            jest.useRealTimers()

            const step: BatchProcessingStep<string, string> = (values) => {
                if (values.some((v) => v.startsWith('poison'))) {
                    throw new TimeoutError()
                }
                return Promise.resolve(values.map((v) => ok(`ok:${v}`)))
            }

            const wrapped = withBatchRetry(step, { tries: 1, sleepMs: 1, splitOnTimeout: true })
            const results = await wrapped(['good', 'poison-1', 'poison-2'])

            expect(results).toHaveLength(3)
            expect(isOkResult(results[0])).toBe(true)
            expect(isDlqResult(results[1])).toBe(true)
            expect(isDlqResult(results[2])).toBe(true)
        })

        it('preserves 1:1 input-to-result ordering across split boundaries', async () => {
            jest.useRealTimers()

            // 8 events with poison at index 3 and 6. The binary splits will
            // slice across multiple boundaries, but every result must map
            // back to its original input position.
            const inputs = ['a', 'b', 'c', 'POISON-1', 'd', 'e', 'POISON-2', 'f']

            const step: BatchProcessingStep<string, string> = (values) => {
                if (values.some((v) => v.startsWith('POISON'))) {
                    throw new TimeoutError()
                }
                // Embed the input value in the output so we can verify ordering
                return Promise.resolve(values.map((v) => ok(`result:${v}`)))
            }

            const wrapped = withBatchRetry(step, { tries: 1, sleepMs: 1, splitOnTimeout: true })
            const results = await wrapped(inputs)

            expect(results).toHaveLength(8)
            for (let i = 0; i < inputs.length; i++) {
                const result = results[i]
                if (inputs[i].startsWith('POISON')) {
                    expect(isDlqResult(result)).toBe(true)
                } else {
                    expect(isOkResult(result)).toBe(true)
                    expect(isOkResult(result) && result.value).toBe(`result:${inputs[i]}`)
                }
            }
        })
    })
})
