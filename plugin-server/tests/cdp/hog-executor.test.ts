import { AsyncFunctionExecutor } from '../../src/cdp/async-function-executor'
import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
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

    const mockAsyncFuntionExecutor = {
        execute: jest.fn(),
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        executor = new HogExecutor(
            config,
            mockFunctionManager as any as HogFunctionManager,
            mockAsyncFuntionExecutor as any as AsyncFunctionExecutor
        )
    })

    describe('general event processing', () => {
        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */
        it('can parse incoming messages correctly', async () => {
            const fn = createHogFunction({
                name: 'Test hog function',
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [1]: fn,
            })

            // Create a message that should be processed by this function
            // Run the function and check that it was executed
            await executor.executeMatchingFunctions(createHogExecutionGlobals())

            expect(mockAsyncFuntionExecutor.execute).toHaveBeenCalledTimes(1)
            expect(mockAsyncFuntionExecutor.execute.mock.calls[0][0]).toMatchObject({
                id: expect.any(String),
                globals: {
                    event: {
                        uuid: 'uuid',
                    },
                },
                teamId: 1,
                hogFunctionId: expect.any(String),
                asyncFunctionName: 'fetch',
                vmState: expect.any(Object),
            })
            expect(mockAsyncFuntionExecutor.execute.mock.calls[0][0].asyncFunctionArgs).toMatchInlineSnapshot(`
                Array [
                  "https://example.com/posthog-webhook",
                  Object {
                    "body": Object {
                      "event": Object {
                        "distinct_id": "distinct_id",
                        "name": "test",
                        "properties": Object {
                          "$lib_version": "1.2.3",
                        },
                        "timestamp": "2024-06-07T12:00:00.000Z",
                        "url": "http://localhost:8000/events/1",
                        "uuid": "uuid",
                      },
                      "event_url": "http://localhost:8000/events/1-test",
                      "groups": null,
                      "nested": Object {
                        "foo": "http://localhost:8000/events/1",
                      },
                      "person": null,
                    },
                    "headers": Object {
                      "version": "v=1.2.3",
                    },
                    "method": "POST",
                    "payload": Object {
                      "event": Object {
                        "distinct_id": "distinct_id",
                        "name": "test",
                        "properties": Object {
                          "$lib_version": "1.2.3",
                        },
                        "timestamp": "2024-06-07T12:00:00.000Z",
                        "url": "http://localhost:8000/events/1",
                        "uuid": "uuid",
                      },
                      "event_url": "http://localhost:8000/events/1-test",
                      "groups": null,
                      "nested": Object {
                        "foo": "http://localhost:8000/events/1",
                      },
                      "person": null,
                    },
                  },
                ]
            `)
        })
        // NOTE: Will be fixed in follow up
        it('can filters incoming messages correctly', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [1]: fn,
            })

            const resultsShouldntMatch = await executor.executeMatchingFunctions(createHogExecutionGlobals())
            expect(resultsShouldntMatch).toHaveLength(0)

            const resultsShouldMatch = await executor.executeMatchingFunctions(
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
})
