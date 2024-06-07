import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { defaultConfig } from '../../src/config/config'
import { PluginsServerConfig } from '../../src/types'
import { RustyHook } from '../../src/worker/rusty-hook'
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

    const mockRustyHook = {
        enqueueIfEnabledForTeam: jest.fn(() => true),
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        executor = new HogExecutor(
            config,
            mockFunctionManager as any as HogFunctionManager,
            mockRustyHook as any as RustyHook
        )
    })

    describe('general event processing', () => {
        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */
        it('can parse incoming messages correctly', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue({
                [1]: fn,
            })

            // Create a message that should be processed by this function
            // Run the function and check that it was executed
            await executor.executeMatchingFunctions({
                globals: createHogExecutionGlobals(),
            })

            expect(mockRustyHook.enqueueIfEnabledForTeam).toHaveBeenCalledTimes(1)
            expect(mockRustyHook.enqueueIfEnabledForTeam.mock.calls[0]).toMatchInlineSnapshot(`
                Array [
                  Object {
                    "pluginConfigId": -3,
                    "pluginId": -3,
                    "teamId": 1,
                    "webhook": Object {
                      "body": "{
                    \\"event\\": {
                        \\"uuid\\": \\"uuid\\",
                        \\"name\\": \\"test\\",
                        \\"distinct_id\\": \\"distinct_id\\",
                        \\"url\\": \\"http://localhost:8000/events/1\\",
                        \\"properties\\": {},
                        \\"timestamp\\": \\"2024-06-07T12:00:00.000Z\\"
                    },
                    \\"groups\\": null,
                    \\"nested\\": {
                        \\"foo\\": \\"http://localhost:8000/events/1\\"
                    },
                    \\"person\\": null,
                    \\"event_url\\": \\"http://localhost:8000/events/1-test\\"
                }",
                      "headers": Object {
                        "version": "v=",
                      },
                      "method": "POST",
                      "url": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                    },
                  },
                ]
            `)
        })
    })
})
