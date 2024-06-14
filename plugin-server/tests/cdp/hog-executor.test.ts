import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionInvocationAsyncResponse, HogFunctionLogEntry, HogFunctionType } from '../../src/cdp/types'
import { defaultConfig } from '../../src/config/config'
import { PluginsServerConfig } from '../../src/types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, createHogFunction, insertHogFunction as _insertHogFunction } from './fixtures'

const config: PluginsServerConfig = {
    ...defaultConfig,
}

describe('Hog Executor', () => {
    jest.setTimeout(1000)
    let executor: HogExecutor

    const mockFunctionManager = {
        reloadAllHogFunctions: jest.fn(),
        getTeamHogFunctions: jest.fn(),
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        executor = new HogExecutor(config, mockFunctionManager as any as HogFunctionManager)
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

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [hogFunction.id]: hogFunction,
            })
        })

        it('can parse incoming messages correctly', () => {
            const results = executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(results).toHaveLength(1)
            expect(results[0]).toMatchObject({
                id: expect.any(String),
                hogFunctionId: hogFunction.id,
            })
        })

        it('collects logs from the function', () => {
            const results = executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(results[0].logs).toMatchObject([
                {
                    team_id: 1,
                    log_source: 'hog_function',
                    log_source_id: hogFunction.id,
                    instance_id: results[0].id,
                    timestamp: '2024-06-07 12:00:00.001',
                    level: 'debug',
                    message: 'Executing function',
                },
                {
                    team_id: 1,
                    log_source: 'hog_function',
                    log_source_id: hogFunction.id,
                    instance_id: results[0].id,
                    timestamp: '2024-06-07 12:00:00.002',
                    level: 'debug',
                    message: "Suspending function due to async function call 'fetch'",
                },
            ])
        })

        it('queues up an async function call', () => {
            const results = executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(results[0].asyncFunction).toMatchObject({
                id: results[0].id,
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
                teamId: 1,
                hogFunctionId: hogFunction.id,
                asyncFunctionName: 'fetch',
                asyncFunctionArgs: [
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
                vmState: expect.any(Object),
            })
        })

        it('executes the full function in a loop', () => {
            const logs: HogFunctionLogEntry[] = []
            const results = executor.executeMatchingFunctions(createHogExecutionGlobals())
            logs.push(...results[0].logs)
            const asyncExecResult = executor.executeAsyncResponse({
                ...results[0].asyncFunction!,
                vmResponse: { status: 200, body: 'success' },
            })

            logs.push(...asyncExecResult.logs)
            expect(asyncExecResult.error).toBeUndefined()
            expect(asyncExecResult.success).toBe(true)
            expect(logs.map((log) => log.message)).toEqual([
                'Executing function',
                "Suspending function due to async function call 'fetch'",
                'Resuming function',
                'Fetch response:, {"status":200,"body":"success"}',
                'Function completed',
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

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [fn.id]: fn,
            })

            const resultsShouldntMatch = executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(resultsShouldntMatch).toHaveLength(0)

            const resultsShouldMatch = executor.executeMatchingFunctions(
                createHogExecutionGlobals({
                    event: {
                        name: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    } as any,
                })
            )
            expect(resultsShouldMatch).toHaveLength(1)
        })
    })

    describe('async function responses', () => {
        it('prevents large looped fetch calls', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.recursive_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [fn.id]: fn,
            })

            // Simulate the recusive loop
            const results = executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(results).toHaveLength(1)

            // Run the result one time simulating a successful fetch
            const asyncResult1 = executor.executeAsyncResponse({
                ...results[0].asyncFunction!,
                vmResponse: { status: 200, body: 'success' },
            })
            expect(asyncResult1.success).toBe(true)
            expect(asyncResult1.asyncFunction).toBeDefined()

            // Run the result one more time simulating a second successful fetch
            const asyncResult2 = executor.executeAsyncResponse({
                ...asyncResult1.asyncFunction!,
                vmResponse: { status: 200, body: 'success' },
            })
            // This time we should see an error for hitting the loop limit
            expect(asyncResult2.success).toBe(false)
            expect(asyncResult2.error).toEqual('Function exceeded maximum async steps')
            expect(asyncResult2.logs.map((log) => log.message)).toEqual(['Function exceeded maximum async steps'])
        })
    })
})
