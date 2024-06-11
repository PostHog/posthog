import { CdpProcessedEventsConsumer } from '../../src/cdp/cdp-processed-events-consumer'
import { defaultConfig } from '../../src/config/config'
import { Hub, PluginsServerConfig, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createIncomingEvent, createMessage, insertHogFunction as _insertHogFunction } from './fixtures'

const config: PluginsServerConfig = {
    ...defaultConfig,
}

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.mock('../../src/utils/fetch', () => {
    return {
        trackedFetch: jest.fn(() => Promise.resolve({ status: 200, text: () => Promise.resolve({}) })),
    }
})

const mockFetch = require('../../src/utils/fetch').trackedFetch

jest.setTimeout(1000)

const noop = () => {}

describe('CDP Processed Events Consuner', () => {
    let processor: CdpProcessedEventsConsumer
    let hub: Hub
    let closeHub: () => Promise<void>
    let team: Team

    const insertHogFunction = async (hogFunction) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeAll(async () => {
        await resetTestDatabase()
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpProcessedEventsConsumer(config, hub.postgres)
        await processor.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub()
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general event processing', () => {
        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */
        it('can parse incoming messages correctly', async () => {
            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
            // Create a message that should be processed by this function
            // Run the function and check that it was executed
            await processor.handleEachBatch(
                [
                    createMessage(
                        createIncomingEvent(team.id, {
                            uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                            event: '$pageview',
                            properties: JSON.stringify({
                                $lib_version: '1.0.0',
                            }),
                        })
                    ),
                ],
                noop
            )

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
                Array [
                  "https://example.com/posthog-webhook",
                  Object {
                    "body": "{
                    \\"event\\": {
                        \\"uuid\\": \\"b3a1fe86-b10c-43cc-acaf-d208977608d0\\",
                        \\"name\\": \\"$pageview\\",
                        \\"distinct_id\\": \\"distinct_id_1\\",
                        \\"properties\\": {
                            \\"$lib_version\\": \\"1.0.0\\",
                            \\"$elements_chain\\": \\"[]\\"
                        },
                        \\"timestamp\\": null,
                        \\"url\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null\\"
                    },
                    \\"groups\\": null,
                    \\"nested\\": {
                        \\"foo\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null\\"
                    },
                    \\"person\\": null,
                    \\"event_url\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null-test\\"
                }",
                    "headers": Object {
                      "version": "v=1.0.0",
                    },
                    "method": "POST",
                    "timeout": 10000,
                  },
                ]
            `)
        })
    })
})
