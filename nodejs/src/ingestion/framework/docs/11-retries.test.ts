/**
 * # Chapter 11: Retry Logic
 *
 * Retry is a per-step option: pass `{ retry }` to `pipe()` or `pipeBatch()` to
 * wrap that single step with automatic retry logic. This handles transient
 * failures like network hiccups, database connection timeouts, or rate limiting.
 *
 * ```
 * .pipe(step, { retry: { tries: 3, sleepMs: 100 } })
 * .pipeBatch(step, { retry: { tries: 3, sleepMs: 100 } })
 * ```
 *
 * ## Key Concepts
 *
 * - **Retriable errors**: Errors marked with `isRetriable: true` are retried
 * - **Non-retriable errors**: Errors marked with `isRetriable: false` go
 *   directly to DLQ without retrying
 * - **Unknown errors**: Errors with no `isRetriable` property are retried, then
 *   rethrown once retries are exhausted (crashes the process - appropriate for
 *   unexpected failures)
 * - **Exponential backoff**: The delay doubles between retries
 * - **Defaults**: 3 tries, 100ms initial sleep
 *
 * `RetryOptions` is `{ name?, tries?, sleepMs? }`. The `name` labels the
 * `ingestion_pipeline_retry_attempts` metric and defaults to the step name.
 *
 * ## Why Retries Wrap a Single Step
 *
 * Retry always wraps exactly one step, never a sequence. Retrying a sequence
 * would re-run steps that already succeeded, which breaks idempotency: if
 * step A writes to a database and step B (a later step) fails, retrying the
 * whole block would run step A's write a second time. Keeping retry scoped to
 * a single step means only the failing operation is repeated. Compose retries
 * by attaching `{ retry }` to each step that needs it, not by wrapping a
 * multi-step block.
 *
 * ## Error Classification
 *
 * Errors carry an `isRetriable` property to indicate whether they should be
 * retried. This distinguishes:
 * - Transient failures (network, timeout) - should retry
 * - Permanent failures (validation, permission) - should not retry
 */
import { ChunkProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { newBatchPipelineBuilder, newPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isDlqResult, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

class RetriableError extends Error {
    isRetriable = true
}

class NonRetriableError extends Error {
    isRetriable = false
}

describe('Single-Step Retries', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * Retriable errors (those with `isRetriable: true`) are automatically
     * retried up to the configured number of times. The step succeeds once
     * the transient condition clears.
     */
    it('retriable errors are retried until the step succeeds', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        function createFlakyStep(): ProcessingStep<Input, { value: string }> {
            return function flakyStep(input) {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('Temporary failure')
                }
                return Promise.resolve(ok({ value: input.value.toUpperCase() }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createFlakyStep(), { retry: { tries: 5, sleepMs: 100 } })
            .build()

        const resultPromise = pipeline.process(createOkContext({ value: 'hello' }, {}))
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries (exponential backoff)
        const result = await resultPromise

        expect(attempts).toBe(3) // Failed twice, succeeded on third
        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value.value).toBe('HELLO')
        }
    })

    /**
     * Non-retriable errors (those with `isRetriable: false`) go directly
     * to DLQ without any retry attempts.
     */
    it('non-retriable errors go directly to DLQ', async () => {
        let attempts = 0

        interface Input {
            data: string
        }

        function createValidationStep(): ProcessingStep<Input, { data: string }> {
            return function validationStep(_input) {
                attempts++
                throw new NonRetriableError('Validation failed - invalid format')
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createValidationStep(), { retry: { tries: 5, sleepMs: 100 } })
            .build()

        // No timer advancement needed - non-retriable errors don't wait
        const result = await pipeline.process(createOkContext({ data: 'bad-data' }, {}))

        expect(attempts).toBe(1) // Only tried once
        expect(isDlqResult(result.result)).toBe(true)
        if (isDlqResult(result.result)) {
            expect(result.result.reason).toContain('non-retriable')
        }
    })

    /**
     * After exhausting the maximum number of retries, a retriable error is
     * rethrown. This is a fatal error - the process should report it and crash
     * rather than continue in a broken state.
     */
    it('after max retries, the error is rethrown', async () => {
        let attempts = 0
        let caughtError: Error | null = null

        interface Input {
            value: string
        }

        function createAlwaysFailsStep(): ProcessingStep<Input, { value: string }> {
            return function alwaysFailsStep(_input) {
                attempts++
                throw new RetriableError(`Attempt ${attempts} failed`)
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createAlwaysFailsStep(), { retry: { tries: 3, sleepMs: 100 } })
            .build()

        const resultPromise = pipeline.process(createOkContext({ value: 'data' }, {})).catch((e) => {
            caughtError = e
        })
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for retries
        await resultPromise

        expect(attempts).toBe(3)
        expect(caughtError).not.toBeNull()
        expect(caughtError!.message).toBe('Attempt 3 failed')
    })

    /**
     * Errors without an `isRetriable` property are retried (in case they are
     * transient), then rethrown once retries are exhausted - never sent to DLQ.
     * This preserves normal crash behavior for unexpected errors.
     */
    it('errors without isRetriable are retried then rethrown', async () => {
        let attempts = 0
        let caughtError: Error | null = null

        interface Input {
            value: string
        }

        function createUnexpectedErrorStep(): ProcessingStep<Input, { value: string }> {
            return function unexpectedErrorStep(_input) {
                attempts++
                throw new Error('Unexpected internal error')
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createUnexpectedErrorStep(), { retry: { tries: 3, sleepMs: 100 } })
            .build()

        const resultPromise = pipeline.process(createOkContext({ value: 'data' }, {})).catch((e) => {
            caughtError = e
        })
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for retries
        await resultPromise

        expect(attempts).toBe(3) // Retried, not short-circuited like a non-retriable error
        expect(caughtError).not.toBeNull()
        expect(caughtError!.message).toBe('Unexpected internal error')
    })
})

describe('Retry Configuration', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * `tries` caps the number of attempts and `sleepMs` sets the initial delay.
     * Subsequent retries use exponential backoff (the delay doubles each time).
     */
    it('tries and sleepMs control attempts and backoff', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        function createSlowlyRecoveringStep(): ProcessingStep<Input, { value: string }> {
            return function slowlyRecoveringStep(input) {
                attempts++
                if (attempts < 4) {
                    throw new RetriableError('Still recovering')
                }
                return Promise.resolve(ok({ value: input.value }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createSlowlyRecoveringStep(), { retry: { tries: 5, sleepMs: 50 } })
            .build()

        const resultPromise = pipeline.process(createOkContext({ value: 'data' }, {}))

        // First attempt happens immediately
        await jest.advanceTimersByTimeAsync(0)
        expect(attempts).toBe(1)

        // After 50ms (initial sleepMs), second attempt
        await jest.advanceTimersByTimeAsync(50)
        expect(attempts).toBe(2)

        // After 100ms more (50 * 2), third attempt
        await jest.advanceTimersByTimeAsync(100)
        expect(attempts).toBe(3)

        // After 200ms more (100 * 2), fourth attempt succeeds
        await jest.advanceTimersByTimeAsync(200)
        expect(attempts).toBe(4)

        await resultPromise
    })

    /**
     * Omitting `tries`/`sleepMs` uses the defaults: 3 tries, 100ms initial sleep.
     */
    it('defaults to 3 tries and 100ms sleep', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        function createFlakyStep(): ProcessingStep<Input, { value: string }> {
            return function flakyStep(input) {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('retry')
                }
                return Promise.resolve(ok({ value: input.value }))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createFlakyStep(), { retry: {} }).build()

        const resultPromise = pipeline.process(createOkContext({ value: 'data' }, {}))
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries (default sleepMs is 100)
        const result = await resultPromise

        expect(isOkResult(result.result)).toBe(true)
        expect(attempts).toBe(3)
    })
})

describe('Batch Retries', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * `pipeBatch(step, { retry })` retries the whole batch step on retriable
     * errors, the same way per-item retry works. The batch is reprocessed as a
     * unit until it succeeds or retries are exhausted.
     */
    it('pipeBatch retries the batch step until it succeeds', async () => {
        let attempts = 0

        interface Event {
            id: number
        }

        function createFlakyBatchStep(): ChunkProcessingStep<Event, Event> {
            return function flakyBatchStep(events) {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('Downstream unavailable')
                }
                return Promise.resolve(events.map((e) => ok(e)))
            }
        }

        const pipeline = newBatchPipelineBuilder<Event>()
            .pipeBatch(createFlakyBatchStep(), { retry: { tries: 5, sleepMs: 100 } })
            .build()

        pipeline.feed([{ id: 1 }, { id: 2 }].map((e) => createOkContext(e, {})))
        const resultsPromise = pipeline.next()
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries
        const results = await resultsPromise

        expect(attempts).toBe(3)
        expect(results).toHaveLength(2)
        expect(results!.every((r) => isOkResult(r.result))).toBe(true)
    })

    /**
     * When a batch step throws a non-retriable error, every input in the batch
     * is converted to its own DLQ result. The failure is attributed per-input
     * so each message is dead-lettered individually.
     */
    it('pipeBatch sends one DLQ per input on a non-retriable error', async () => {
        interface Event {
            id: number
        }

        function createFailingBatchStep(): ChunkProcessingStep<Event, Event> {
            return function failingBatchStep(_events) {
                throw new NonRetriableError('Batch permanently invalid')
            }
        }

        const pipeline = newBatchPipelineBuilder<Event>()
            .pipeBatch(createFailingBatchStep(), { retry: { tries: 5, sleepMs: 100 } })
            .build()

        // Three inputs -> three DLQ results, no retries (non-retriable)
        pipeline.feed([{ id: 1 }, { id: 2 }, { id: 3 }].map((e) => createOkContext(e, {})))
        const results = await pipeline.next()

        expect(results).toHaveLength(3)
        expect(results!.every((r) => isDlqResult(r.result))).toBe(true)
    })
})
