import { OVERFLOW_OUTPUT } from '../common/outputs'
import { BatchRetryStepResult, withBatchRetry } from './batch-retry'
import { PipelineResultType, drop, isDlqResult, isDropResult, isOkResult, isRedirectResult, ok } from './results'

jest.mock('~/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

jest.mock('prom-client', () => {
    const actual = jest.requireActual('prom-client')
    const registry = new actual.Registry()
    return {
        ...actual,
        Counter: class FakeCounter {
            labels() {
                return { inc: jest.fn() }
            }
        },
        register: registry,
    }
})

type StepFn = jest.MockedFunction<(inputs: string[]) => Promise<BatchRetryStepResult<string>[]>>

function createMockStep(): StepFn {
    return jest.fn<Promise<BatchRetryStepResult<string>[]>, [string[]]>()
}

function succeeded(value: string): BatchRetryStepResult<string> {
    return { status: 'success', result: ok(value) }
}

function dropped(reason: string): BatchRetryStepResult<string> {
    return { status: 'success', result: drop(reason) }
}

function failed(reason: string, retriable = true): BatchRetryStepResult<string> {
    return { status: 'failed', retriable, reason }
}

describe('withBatchRetry', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('success passthrough', () => {
        it('passes through ok results unchanged', async () => {
            const step = createMockStep()
            step.mockResolvedValue([succeeded('a'), succeeded('b'), succeeded('c')])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['x', 'y', 'z'])

            expect(results).toHaveLength(3)
            expect(results.every(isOkResult)).toBe(true)
            expect(results.map((r) => (isOkResult(r) ? r.value : null))).toEqual(['a', 'b', 'c'])
        })

        it('passes through drop results unchanged', async () => {
            const step = createMockStep()
            step.mockResolvedValue([dropped('filtered'), dropped('spam')])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['x', 'y'])

            expect(results).toHaveLength(2)
            expect(results.every(isDropResult)).toBe(true)
        })
    })

    describe('failure routing', () => {
        it('sends non-retriable failures to DLQ', async () => {
            const step = createMockStep()
            step.mockResolvedValue([failed('bad data', false)])

            const wrapped = withBatchRetry(step, { maxAttempts: 3, retrySleepMs: 0 })
            const results = await wrapped(['x'])

            expect(step).toHaveBeenCalledTimes(1)
            expect(results).toHaveLength(1)
            expect(isDlqResult(results[0])).toBe(true)
            if (isDlqResult(results[0])) {
                expect(results[0].reason).toBe('bad data')
            }
        })

        it('overflows retriable failures when some events succeeded', async () => {
            const step = createMockStep()
            step.mockResolvedValue([succeeded('ok'), failed('timeout')])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['a', 'b'])

            expect(results).toHaveLength(2)
            expect(isOkResult(results[0])).toBe(true)
            expect(isRedirectResult(results[1])).toBe(true)
            if (isRedirectResult(results[1])) {
                expect(results[1].output).toBe(OVERFLOW_OUTPUT)
                expect(results[1].reason).toBe('timeout')
            }
        })

        it('overflows all events when all fail with retriable errors', async () => {
            const step = createMockStep()
            step.mockResolvedValue([failed('service down')])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['x'])

            expect(results).toHaveLength(1)
            expect(isRedirectResult(results[0])).toBe(true)
        })
    })

    describe('retry behavior', () => {
        it('only passes failed events to retry attempts, not successful ones', async () => {
            const step = createMockStep()
            step.mockResolvedValueOnce([succeeded('a'), failed('oops')])
            step.mockResolvedValueOnce([succeeded('b')])

            const wrapped = withBatchRetry(step, { maxAttempts: 2, retrySleepMs: 10 })
            const resultPromise = wrapped(['x', 'y'])
            await jest.runAllTimersAsync()
            const results = await resultPromise

            expect(step).toHaveBeenCalledTimes(2)
            expect(step.mock.calls[0][0]).toEqual(['x', 'y'])
            expect(step.mock.calls[1][0]).toEqual(['y'])

            expect(results).toHaveLength(2)
            expect(isOkResult(results[0])).toBe(true)
            expect(isOkResult(results[1])).toBe(true)
        })

        it('succeeds on second attempt when first attempt partially fails', async () => {
            const step = createMockStep()
            step.mockResolvedValueOnce([failed('timeout'), succeeded('b')])
            step.mockResolvedValueOnce([succeeded('a-retried')])

            const wrapped = withBatchRetry(step, { maxAttempts: 2, retrySleepMs: 10 })
            const resultPromise = wrapped(['x', 'y'])
            await jest.runAllTimersAsync()
            const results = await resultPromise

            expect(results).toHaveLength(2)
            expect(isOkResult(results[0])).toBe(true)
            if (isOkResult(results[0])) {
                expect(results[0].value).toBe('a-retried')
            }
            expect(isOkResult(results[1])).toBe(true)
            if (isOkResult(results[1])) {
                expect(results[1].value).toBe('b')
            }
        })

        it('calls the step at most maxAttempts times for persistent failures', async () => {
            const step = createMockStep()
            step.mockResolvedValue([failed('always fails')])

            const wrapped = withBatchRetry(step, { maxAttempts: 3, retrySleepMs: 10 })
            const resultPromise = wrapped(['x'])
            await jest.runAllTimersAsync()
            const results = await resultPromise

            expect(step).toHaveBeenCalledTimes(3)
            expect(results).toHaveLength(1)
            expect(isRedirectResult(results[0])).toBe(true)
        })

        it('preserves original index ordering with mixed results across retries', async () => {
            const step = createMockStep()
            step.mockResolvedValueOnce([
                succeeded('result-0'),
                failed('err'),
                succeeded('result-2'),
                failed('err'),
                succeeded('result-4'),
            ])
            step.mockResolvedValueOnce([succeeded('result-1'), succeeded('result-3')])

            const wrapped = withBatchRetry(step, { maxAttempts: 2, retrySleepMs: 10 })
            const resultPromise = wrapped(['e0', 'e1', 'e2', 'e3', 'e4'])
            await jest.runAllTimersAsync()
            const results = await resultPromise

            expect(results).toHaveLength(5)
            expect(results.map((r) => (isOkResult(r) ? r.value : 'NOT_OK'))).toEqual([
                'result-0',
                'result-1',
                'result-2',
                'result-3',
                'result-4',
            ])
        })
    })

    describe('thrown errors propagate', () => {
        it('propagates unexpected errors from the step', async () => {
            const step = createMockStep()
            step.mockRejectedValue(new Error('unexpected crash'))

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })

            await expect(wrapped(['x'])).rejects.toThrow('unexpected crash')
        })
    })

    describe('mixed results', () => {
        it('handles a batch containing ok, drop, and non-retriable failure', async () => {
            const step = createMockStep()
            step.mockResolvedValueOnce([succeeded('value'), dropped('filtered'), failed('err', false)])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['a', 'b', 'c'])

            expect(results).toHaveLength(3)
            expect(isOkResult(results[0])).toBe(true)
            expect(isDropResult(results[1])).toBe(true)
            expect(isDlqResult(results[2])).toBe(true)
        })
    })

    describe('step name', () => {
        it('preserves step name on the returned function', () => {
            function myNamedStep(_inputs: string[]): Promise<BatchRetryStepResult<string>[]> {
                return Promise.resolve([])
            }

            const wrapped = withBatchRetry(myNamedStep)
            expect(wrapped.name).toBe('myNamedStep')
        })
    })

    describe('DLQ for non-retriable results', () => {
        it('returns DLQ pipeline result for non-retriable failures', async () => {
            const step = createMockStep()
            step.mockResolvedValue([succeeded('ok'), failed('invalid format', false)])

            const wrapped = withBatchRetry(step, { maxAttempts: 1 })
            const results = await wrapped(['a', 'b'])

            expect(results).toHaveLength(2)
            expect(isOkResult(results[0])).toBe(true)
            expect(isDlqResult(results[1])).toBe(true)
            if (isDlqResult(results[1])) {
                expect(results[1].type).toBe(PipelineResultType.DLQ)
                expect(results[1].reason).toBe('invalid format')
            }
        })
    })
})
