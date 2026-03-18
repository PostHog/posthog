/**
 * # Chapter 11: Retry Logic
 *
 * The `retry()` wrapper provides automatic retry logic for transient failures.
 * This is essential for handling temporary issues like network hiccups,
 * database connection timeouts, or rate limiting.
 *
 * ## Key Concepts
 *
 * - **Retriable errors**: Errors marked with `isRetriable: true` are retried
 * - **Non-retriable errors**: Sent directly to DLQ without retrying
 * - **Exponential backoff**: Delays increase between retries
 * - **Max retries**: After exhausting retries, the error is rethrown
 *
 * ## Error Classification
 *
 * Errors must have an `isRetriable` property to indicate whether they should
 * be retried. This allows distinguishing between:
 * - Transient failures (network, timeout) - should retry
 * - Permanent failures (validation, permission) - should not retry
 */
import { newPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { isDlqResult, isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'

class RetriableError extends Error {
    isRetriable = true
}

class NonRetriableError extends Error {
    isRetriable = false
}

describe('Retry Basics', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * Retriable errors (those with `isRetriable: true`) are automatically
     * retried up to the configured number of times.
     */
    it('retriable errors are automatically retried', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createFlakyStep(): ProcessingStep<Input, Output> {
            return function flakyStep(input) {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('Temporary failure')
                }
                return Promise.resolve(ok({ value: input.value.toUpperCase() }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createFlakyStep()), { tries: 5, sleepMs: 100 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'hello' })))
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries (exponential backoff)
        const result = await resultPromise

        expect(attempts).toBe(3) // Failed twice, succeeded on third
        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value.value).toBe('HELLO')
        }
    })

    /**
     * When a retry occurs, the entire sub-pipeline is re-executed from the
     * beginning, not just the failing step.
     */
    it('retries run the entire sub-pipeline again', async () => {
        const stepCalls: string[] = []
        let step2Attempts = 0

        interface Input {
            value: string
        }

        function createStep1(): ProcessingStep<Input, Input> {
            return function step1(input) {
                stepCalls.push('step1')
                return Promise.resolve(ok(input))
            }
        }

        function createStep2(): ProcessingStep<Input, Input> {
            return function step2(input) {
                stepCalls.push('step2')
                step2Attempts++
                if (step2Attempts < 3) {
                    throw new RetriableError('Step 2 failed')
                }
                return Promise.resolve(ok(input))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createStep1()).pipe(createStep2()), { tries: 5, sleepMs: 100 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' })))
        await jest.advanceTimersByTimeAsync(300)
        await resultPromise

        // Each retry runs both steps: step1, step2 (fail), step1, step2 (fail), step1, step2 (success)
        expect(stepCalls).toEqual(['step1', 'step2', 'step1', 'step2', 'step1', 'step2'])
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

        interface Output {
            data: string
        }

        function createValidationStep(): ProcessingStep<Input, Output> {
            return function validationStep(_input) {
                attempts++
                throw new NonRetriableError('Validation failed - invalid format')
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createValidationStep()), { tries: 5, sleepMs: 100 })
            .build()

        // No timer advancement needed - non-retriable errors don't wait
        const result = await pipeline.process(createContext(ok({ data: 'bad-data' })))

        expect(attempts).toBe(1) // Only tried once
        expect(isDlqResult(result.result)).toBe(true)
        if (isDlqResult(result.result)) {
            expect(result.result.reason).toContain('non-retriable')
        }
    })

    /**
     * When retries use exponential backoff, the delay between retries
     * increases to avoid overwhelming a struggling service.
     */
    it('retries use exponential backoff', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createSlowlyRecoveringStep(): ProcessingStep<Input, Output> {
            return function slowlyRecoveringStep(input) {
                attempts++
                if (attempts < 4) {
                    throw new RetriableError('Still recovering')
                }
                return Promise.resolve(ok({ value: input.value }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createSlowlyRecoveringStep()), { tries: 5, sleepMs: 100 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' })))

        // First attempt happens immediately
        await jest.advanceTimersByTimeAsync(0)
        expect(attempts).toBe(1)

        // After 100ms, second attempt
        await jest.advanceTimersByTimeAsync(100)
        expect(attempts).toBe(2)

        // After 200ms more (exponential), third attempt
        await jest.advanceTimersByTimeAsync(200)
        expect(attempts).toBe(3)

        // After 400ms more (exponential), fourth attempt succeeds
        await jest.advanceTimersByTimeAsync(400)
        expect(attempts).toBe(4)

        await resultPromise
    })

    /**
     * After exhausting the maximum number of retries, the error is rethrown.
     * This is a fatal error - the process should report it and crash rather
     * than continue in a broken state.
     */
    it('after max retries, the error is rethrown and the process should crash', async () => {
        let attempts = 0
        let caughtError: Error | null = null

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createAlwaysFailsStep(): ProcessingStep<Input, Output> {
            return function alwaysFailsStep(_input) {
                attempts++
                throw new RetriableError(`Attempt ${attempts} failed`)
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createAlwaysFailsStep()), { tries: 3, sleepMs: 100 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' }))).catch((e) => {
            caughtError = e
        })
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for retries
        await resultPromise

        expect(attempts).toBe(3)
        expect(caughtError).not.toBeNull()
        expect(caughtError!.message).toBe('Attempt 3 failed')
    })

    /**
     * Errors without an `isRetriable` property are rethrown (not caught).
     * This preserves normal error handling for unexpected errors.
     */
    it('errors without isRetriable flag are rethrown', async () => {
        let caughtError: Error | null = null

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createUnexpectedErrorStep(): ProcessingStep<Input, Output> {
            return function unexpectedErrorStep(_input) {
                throw new Error('Unexpected internal error')
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createUnexpectedErrorStep()), { tries: 3, sleepMs: 100 })
            .build()

        // Errors without isRetriable are retried but then rethrown (not sent to DLQ)
        const resultPromise = pipeline.process(createContext(ok({ value: 'data' }))).catch((e) => {
            caughtError = e
        })
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for retries
        await resultPromise

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
     * The `tries` option controls the maximum number of attempts before
     * giving up.
     */
    it('tries option controls maximum attempts', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createAlwaysFailsStep(): ProcessingStep<Input, Output> {
            return function alwaysFailsStep(_input) {
                attempts++
                throw new RetriableError('fail')
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createAlwaysFailsStep()), { tries: 2, sleepMs: 100 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' }))).catch(() => {
            // Expected to throw after max retries
        })
        await jest.advanceTimersByTimeAsync(100) // One retry (100ms between attempts)
        await resultPromise

        expect(attempts).toBe(2)
    })

    /**
     * The `sleepMs` option sets the initial delay between retries.
     * Subsequent retries use exponential backoff (delay doubles each time).
     */
    it('sleepMs option sets initial delay with exponential backoff', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createSlowlyRecoveringStep(): ProcessingStep<Input, Output> {
            return function slowlyRecoveringStep(input) {
                attempts++
                if (attempts < 4) {
                    throw new RetriableError('Still recovering')
                }
                return Promise.resolve(ok({ value: input.value }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createSlowlyRecoveringStep()), { tries: 5, sleepMs: 50 })
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' })))

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
     * Default retry configuration is used when not specified.
     */
    it('default retry configuration (3 tries, 100ms sleep)', async () => {
        let attempts = 0

        interface Input {
            value: string
        }

        interface Output {
            value: string
        }

        function createFlakyStep(): ProcessingStep<Input, Output> {
            return function flakyStep(input) {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('retry')
                }
                return Promise.resolve(ok({ value: input.value }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .retry((builder) => builder.pipe(createFlakyStep()))
            .build()

        const resultPromise = pipeline.process(createContext(ok({ value: 'data' })))
        await jest.advanceTimersByTimeAsync(300) // 100ms + 200ms for two retries (default sleepMs is 100)
        const result = await resultPromise

        expect(isOkResult(result.result)).toBe(true)
        expect(attempts).toBe(3)
    })
})
