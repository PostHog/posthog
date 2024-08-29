import { DateTime } from 'luxon'

import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionAsyncFunctionResponse, HogFunctionType } from '../../src/cdp/types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import {
    createHogExecutionGlobals,
    createHogFunction,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from './fixtures'

const createAsyncFunctionResponse = (response?: Record<string, any>): HogFunctionAsyncFunctionResponse => {
    return {
        timings: [
            {
                kind: 'async_function',
                duration_ms: 100,
            },
        ],
        response: {
            status: 200,
            body: 'success',
            ...response,
        },
    }
}

describe('Hog Executor', () => {
    jest.setTimeout(1000)
    let executor: HogExecutor

    const mockFunctionManager = {
        reloadAllHogFunctions: jest.fn(),
        getTeamHogFunctions: jest.fn(),
        getTeamHogFunction: jest.fn(),
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        executor = new HogExecutor(mockFunctionManager as any as HogFunctionManager)
    })

    describe('general event processing', () => {
        let hogFunction: HogFunctionType
        beforeEach(() => {
            hogFunction = createHogFunction({
                name: 'Test hog function',
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([hogFunction])
            mockFunctionManager.getTeamHogFunction.mockReturnValue(hogFunction)
        })

        it('can execute an invocation', () => {
            const invocation = createInvocation(hogFunction)
            const result = executor.execute(invocation)
            expect(result).toEqual({
                capturedPostHogEvents: [],
                invocation: {
                    id: expect.any(String),
                    teamId: 1,
                    globals: invocation.globals,
                    hogFunction: invocation.hogFunction,
                    queue: 'fetch',
                    queueParameters: expect.any(Object),
                    timings: [
                        {
                            kind: 'hog',
                            duration_ms: 0,
                        },
                    ],
                    vmState: expect.any(Object),
                },
                finished: false,
                logs: expect.any(Array),
            })
        })

        it('collects logs from the function', () => {
            const invocation = createInvocation(hogFunction)
            const result = executor.execute(invocation)
            expect(result.logs).toMatchObject([
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: 'Executing function',
                },
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: "Suspending function due to async function call 'fetch'. Payload: 1768 bytes",
                },
            ])
        })

        it('redacts secret values from the logs', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.input_printer,
                ...HOG_INPUTS_EXAMPLES.secret_inputs,
            })
            const invocation = createInvocation(fn)
            const result = executor.execute(invocation)

            expect(result.logs.map((x) => x.message)).toMatchInlineSnapshot(`
                Array [
                  "Executing function",
                  "test",
                  "{\\"nested\\":{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false}}",
                  "{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false}",
                  "substring: ***REDACTED***",
                  "{\\"input_1\\":\\"test\\",\\"secret_input_2\\":{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false},\\"secret_input_3\\":\\"***REDACTED***\\"}",
                  "Function completed in 0ms. Sync: 0ms. Mem: 169 bytes. Ops: 28.",
                ]
            `)
        })

        it('queues up an async function call', () => {
            const invocation = createInvocation(hogFunction)
            const result = executor.execute(invocation)

            expect(result.invocation).toMatchObject({
                queue: 'fetch',
                queueParameters: {
                    url: 'https://example.com/posthog-webhook',
                    method: 'POST',
                    headers: { version: 'v=1.2.3' },
                },
            })

            expect(JSON.parse(result.invocation.queueParameters!.body)).toEqual({
                event: {
                    uuid: 'uuid',
                    name: 'test',
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: { $lib_version: '1.2.3' },
                    timestamp: '2024-06-07T12:00:00.000Z',
                },
                groups: {},
                nested: { foo: 'http://localhost:8000/events/1' },
                person: {
                    uuid: 'uuid',
                    name: 'test',
                    url: 'http://localhost:8000/persons/1',
                    properties: { email: 'test@posthog.com' },
                },
                event_url: 'http://localhost:8000/events/1-test',
            })
        })

        it('executes the full function in a loop', () => {
            const result = executor.execute(createInvocation(hogFunction))
            const logs = result.logs.splice(0, 100)

            expect(result.finished).toBe(false)
            expect(result.invocation.queue).toBe('fetch')
            expect(result.invocation.vmState).toBeDefined()

            // Simulate what the callback does
            result.invocation.queue = 'hog'
            result.invocation.queueParameters = createAsyncFunctionResponse()

            const secondResult = executor.execute(result.invocation)
            logs.push(...secondResult.logs)

            expect(secondResult.finished).toBe(true)
            expect(secondResult.error).toBeUndefined()
            expect(logs.map((log) => log.message)).toMatchInlineSnapshot(`
                Array [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1768 bytes",
                  "Resuming function",
                  "Fetch response:, {\\"status\\":200,\\"body\\":\\"success\\"}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 750 bytes. Ops: 22.",
                ]
            `)
        })

        it('parses the responses body if a string', () => {
            const result = executor.execute(createInvocation(hogFunction))
            const logs = result.logs.splice(0, 100)
            result.invocation.queue = 'hog'
            result.invocation.queueParameters = createAsyncFunctionResponse({
                body: JSON.stringify({ foo: 'bar' }),
            })

            const secondResult = executor.execute(result.invocation)
            logs.push(...secondResult.logs)

            expect(logs.map((log) => log.message)).toMatchInlineSnapshot(`
                Array [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1768 bytes",
                  "Resuming function",
                  "Fetch response:, {\\"status\\":200,\\"body\\":{\\"foo\\":\\"bar\\"}}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 750 bytes. Ops: 22.",
                ]
            `)
        })
    })

    describe('filtering', () => {
        it('can filters incoming messages correctly', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

            const resultsShouldntMatch = executor.findMatchingFunctions(createHogExecutionGlobals({ groups: {} }))
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

            const resultsShouldMatch = executor.findMatchingFunctions(
                createHogExecutionGlobals({
                    groups: {},
                    event: {
                        name: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    } as any,
                })
            )
            expect(resultsShouldMatch.matchingFunctions).toHaveLength(1)
            expect(resultsShouldMatch.nonMatchingFunctions).toHaveLength(0)
        })
    })

    describe('async functions', () => {
        it('prevents large looped fetch calls', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.recursive_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            // Simulate the recusive loop
            const invocation = createInvocation(fn)

            // Start the function
            const result1 = executor.execute(invocation)
            // Run the response one time simulating a successful fetch
            result1.invocation.queue = 'hog'
            result1.invocation.queueParameters = createAsyncFunctionResponse()
            const result2 = executor.execute(result1.invocation)
            expect(result2.finished).toBe(false)
            expect(result2.error).toBe(undefined)
            expect(result2.invocation.queue).toBe('fetch')

            // This time we should see an error for hitting the loop limit
            result2.invocation.queue = 'hog'
            result2.invocation.queueParameters = createAsyncFunctionResponse()
            const result3 = executor.execute(result1.invocation)
            expect(result3.finished).toBe(false)
            expect(result3.error).toEqual('Exceeded maximum number of async steps: 2')
            expect(result3.logs.map((log) => log.message)).toEqual([
                'Resuming function',
                'Error executing function: HogVMException: Exceeded maximum number of async steps: 2',
            ])
        })
    })

    describe('slow functions', () => {
        beforeEach(() => {
            // We need to use real timers for this test as the timeout is based on real time
            jest.useRealTimers()
        })
        it('limits the execution time and exits appropriately', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.malicious_function,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

            const result = executor.execute(createInvocation(fn))
            expect(result.error).toContain('Execution timed out after 0.1 seconds. Performed ')

            expect(result.logs.map((log) => log.message)).toEqual([
                'Executing function',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'Function exceeded maximum log entries. No more logs will be collected.',
                expect.stringContaining(
                    'Error executing function: HogVMException: Execution timed out after 0.1 seconds. Performed'
                ),
            ])
        })
    })

    describe('posthogCaptue', () => {
        it('captures events', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = executor.execute(createInvocation(fn))
            expect(result?.capturedPostHogEvents).toEqual([
                {
                    distinct_id: 'distinct_id',
                    event: 'test (copy)',
                    properties: {
                        $hog_function_execution_count: 1,
                    },
                    team_id: 1,
                    timestamp: '2024-06-07T12:00:00.000Z',
                },
            ])
        })

        it('ignores events that have already used their posthogCapture', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({
                groups: {},
                event: {
                    properties: {
                        $hog_function_execution_count: 1,
                    },
                },
            } as any)
            const result = executor.execute(createInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toEqual([])
            expect(result?.logs[1].message).toMatchInlineSnapshot(
                `"postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured."`
            )
        })
    })
})
