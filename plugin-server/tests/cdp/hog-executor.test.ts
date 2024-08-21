import { DateTime } from 'luxon'

import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import {
    HogFunctionAsyncFunctionResponse,
    HogFunctionInvocationResult,
    HogFunctionType,
    LogEntry,
} from '../../src/cdp/types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, createHogFunction, insertHogFunction as _insertHogFunction } from './fixtures'

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

        it('can execute messages', () => {
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            expect(results).toHaveLength(1)
            expect(results[0]).toMatchObject({
                invocation: {
                    id: expect.any(String),
                    hogFunctionId: hogFunction.id,
                },
                finished: false,
                asyncFunctionRequest: {},
            })
        })

        it('collects logs from the function', () => {
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            expect(results[0].logs).toMatchObject([
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: 'Executing function',
                },
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: "Suspending function due to async function call 'fetch'. Payload: 1299 bytes",
                },
            ])
        })

        it('redacts secret values from the logs', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.input_printer,
                ...HOG_INPUTS_EXAMPLES.secret_inputs,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

            const result = executor.executeFunction(createHogExecutionGlobals(), fn) as HogFunctionInvocationResult
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
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            expect(results[0]).toMatchObject({
                invocation: {
                    id: results[0].invocation.id,
                    teamId: 1,
                    hogFunctionId: hogFunction.id,
                    vmState: expect.any(Object),
                    globals: {
                        project: { id: 1, name: 'test', url: 'http://localhost:8000/projects/1' },
                        event: {
                            uuid: 'uuid',
                            name: 'test',
                            distinct_id: 'distinct_id',
                            url: 'http://localhost:8000/events/1',
                            properties: { $lib_version: '1.2.3' },
                            timestamp: '2024-06-07T12:00:00.000Z',
                        },
                        source: {
                            name: 'Test hog function',
                            url: `http://localhost:8000/projects/1/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                        },
                    },
                    timings: [
                        {
                            kind: 'hog',
                            duration_ms: 0,
                        },
                    ],
                },

                asyncFunctionRequest: {
                    name: 'fetch',
                    args: [
                        'https://example.com/posthog-webhook',
                        {
                            headers: { version: 'v=1.2.3' },
                            body: {
                                event: {
                                    uuid: 'uuid',
                                    name: 'test',
                                    distinct_id: 'distinct_id',
                                    url: 'http://localhost:8000/events/1',
                                    properties: { $lib_version: '1.2.3' },
                                    timestamp: '2024-06-07T12:00:00.000Z',
                                },
                                groups: null,
                                nested: { foo: 'http://localhost:8000/events/1' },
                                person: null,
                                event_url: 'http://localhost:8000/events/1-test',
                            },
                            method: 'POST',
                        },
                    ],
                },
            })
        })

        it('executes the full function in a loop', () => {
            const logs: LogEntry[] = []
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            const splicedLogs = results[0].logs.splice(0, 100)
            logs.push(...splicedLogs)

            const asyncExecResult = executor.executeAsyncResponse(results[0].invocation, createAsyncFunctionResponse())

            logs.push(...asyncExecResult.logs)
            expect(asyncExecResult.error).toBeUndefined()
            expect(asyncExecResult.finished).toBe(true)
            expect(logs.map((log) => log.message)).toEqual([
                'Executing function',
                "Suspending function due to async function call 'fetch'. Payload: 1299 bytes",
                'Resuming function',
                'Fetch response:, {"status":200,"body":"success"}',
                'Function completed in 100ms. Sync: 0ms. Mem: 589 bytes. Ops: 22.',
            ])
        })

        it('parses the responses body if a string', () => {
            const logs: LogEntry[] = []
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            const splicedLogs = results[0].logs.splice(0, 100)
            logs.push(...splicedLogs)

            const asyncExecResult = executor.executeAsyncResponse(
                results[0].invocation,
                createAsyncFunctionResponse({
                    body: JSON.stringify({ foo: 'bar' }),
                })
            )

            logs.push(...asyncExecResult.logs)
            expect(asyncExecResult.error).toBeUndefined()
            expect(asyncExecResult.finished).toBe(true)
            expect(logs.map((log) => log.message)).toEqual([
                'Executing function',
                "Suspending function due to async function call 'fetch'. Payload: 1299 bytes",
                'Resuming function',
                'Fetch response:, {"status":200,"body":{"foo":"bar"}}', // The body is parsed
                'Function completed in 100ms. Sync: 0ms. Mem: 589 bytes. Ops: 22.',
            ])
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

            const resultsShouldntMatch = executor.findMatchingFunctions(createHogExecutionGlobals())
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

            const resultsShouldMatch = executor.findMatchingFunctions(
                createHogExecutionGlobals({
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

    describe('async function responses', () => {
        it('prevents large looped fetch calls', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.recursive_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

            // Simulate the recusive loop
            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            expect(results).toHaveLength(1)

            // Run the result one time simulating a successful fetch
            const asyncResult1 = executor.executeAsyncResponse(results[0].invocation, createAsyncFunctionResponse())
            expect(asyncResult1.finished).toBe(false)
            expect(asyncResult1.error).toBe(undefined)
            expect(asyncResult1.asyncFunctionRequest).toBeDefined()

            // Run the result one more time simulating a second successful fetch
            const asyncResult2 = executor.executeAsyncResponse(asyncResult1.invocation, createAsyncFunctionResponse())
            // This time we should see an error for hitting the loop limit
            expect(asyncResult2.finished).toBe(false)
            expect(asyncResult2.error).toEqual('Exceeded maximum number of async steps: 2')
            expect(asyncResult2.logs.map((log) => log.message)).toEqual([
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

            const globals = createHogExecutionGlobals()
            const results = executor
                .findMatchingFunctions(createHogExecutionGlobals())
                .matchingFunctions.map((x) => executor.executeFunction(globals, x) as HogFunctionInvocationResult)
            expect(results).toHaveLength(1)
            expect(results[0].error).toContain('Execution timed out after 0.1 seconds. Performed ')

            expect(results[0].logs.map((log) => log.message)).toEqual([
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

            const globals = createHogExecutionGlobals()
            const result = executor.executeFunction(globals, fn)
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
                event: {
                    properties: {
                        $hog_function_execution_count: 1,
                    },
                },
            } as any)
            const result = executor.executeFunction(globals, fn)
            expect(result?.capturedPostHogEvents).toEqual([])
            expect(result?.logs[1].message).toMatchInlineSnapshot(
                `"postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured."`
            )
        })
    })
})
