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
})
