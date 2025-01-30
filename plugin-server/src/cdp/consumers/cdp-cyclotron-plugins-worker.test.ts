import { DateTime } from 'luxon'

import {
    createHogExecutionGlobals,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from '~/tests/cdp/fixtures'
import { getProducedKafkaMessages, getProducedKafkaMessagesForTopic } from '~/tests/helpers/mocks/producer.mock'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { DESTINATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronWorkerPlugins } from './cdp-cyclotron-plugins-worker.consumer'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('CdpCyclotronWorkerPlugins', () => {
    let processor: CdpCyclotronWorkerPlugins
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs
    let mockFetch: jest.Mock
    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, {
            ...hogFunction,
            type: 'destination',
        })
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    const intercomPlugin = DESTINATION_PLUGINS_BY_ID['posthog-intercom-plugin']

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub)
        processor = new CdpCyclotronWorkerPlugins(hub)

        await processor.start()

        processor['pluginExecutor'].fetch = mockFetch = jest.fn(() =>
            Promise.resolve({
                status: 200,
                json: () =>
                    Promise.resolve({
                        status: 200,
                    }),
            } as any)
        )

        jest.spyOn(processor['cyclotronWorker']!, 'updateJob').mockImplementation(() => {})
        jest.spyOn(processor['cyclotronWorker']!, 'releaseJob').mockImplementation(() => Promise.resolve())

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        fn = await insertHogFunction({
            name: 'Plugin test',
            template_id: 'plugin-posthog-intercom-plugin',
        })
        globals = {
            ...createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                        $lib_version: '1.0.0',
                        $set: {
                            email: 'test@posthog.com',
                        },
                    },
                    timestamp: fixedTime.toISO(),
                } as any,
            }),
            inputs: {
                intercomApiKey: '1234567890',
                triggeringEvents: '$identify,mycustomevent',
                ignoredEmailDomains: 'dev.posthog.com',
                useEuropeanDataStorage: 'No',
            },
        }
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('setupPlugin', () => {
        it('should setup a plugin on first call', async () => {
            jest.spyOn(intercomPlugin, 'setupPlugin')

            const results = processor.processBatch([
                createInvocation(fn, globals),
                createInvocation(fn, globals),
                createInvocation(fn, globals),
            ])

            expect(await results).toMatchObject([{ finished: true }, { finished: true }, { finished: true }])

            expect(intercomPlugin.setupPlugin).toHaveBeenCalledTimes(1)
            expect(jest.mocked(intercomPlugin.setupPlugin!).mock.calls[0][0]).toMatchInlineSnapshot(`
                {
                  "config": {
                    "ignoredEmailDomains": "dev.posthog.com",
                    "intercomApiKey": "1234567890",
                    "triggeringEvents": "$identify,mycustomevent",
                    "useEuropeanDataStorage": "No",
                  },
                  "fetch": [Function],
                  "global": {},
                  "logger": {
                    "debug": [Function],
                    "error": [Function],
                    "log": [Function],
                    "warn": [Function],
                  },
                }
            `)
        })
    })

    describe('onEvent', () => {
        it('should call the plugin onEvent method', async () => {
            jest.spyOn(intercomPlugin as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
            })

            await processor.processBatch([invocation])

            expect(intercomPlugin.onEvent).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(intercomPlugin.onEvent!).mock.calls[0][0])).toMatchInlineSnapshot(`
                {
                  "distinct_id": "distinct_id",
                  "event": "mycustomevent",
                  "person": {
                    "created_at": "",
                    "properties": {
                      "email": "test@posthog.com",
                      "first_name": "Pumpkin",
                    },
                    "team_id": 2,
                    "uuid": "uuid",
                  },
                  "properties": {
                    "email": "test@posthog.com",
                  },
                  "team_id": 2,
                  "timestamp": "2025-01-01T00:00:00.000Z",
                  "uuid": "<REPLACED-UUID-0>",
                }
            `)

            expect(mockFetch).toHaveBeenCalledTimes(2)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api.intercom.io/contacts/search",
                  {
                    "body": "{"query":{"field":"email","operator":"=","value":"test@posthog.com"}}",
                    "headers": {
                      "Accept": "application/json",
                      "Authorization": "Bearer 1234567890",
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)
            expect(forSnapshot(mockFetch.mock.calls[1])).toMatchInlineSnapshot(`
                [
                  "https://api.intercom.io/events",
                  {
                    "body": "{"event_name":"mycustomevent","created_at":null,"email":"test@posthog.com","id":"distinct_id"}",
                    "headers": {
                      "Accept": "application/json",
                      "Authorization": "Bearer 1234567890",
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(forSnapshot(jest.mocked(processor['cyclotronWorker']!.updateJob).mock.calls)).toMatchInlineSnapshot(`
                [
                  [
                    "<REPLACED-UUID-0>",
                    "completed",
                  ],
                ]
            `)
        })

        it('should mock out fetch if it is a test function', async () => {
            jest.spyOn(intercomPlugin as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.hogFunction.name = 'My function [CDP-TEST-HIDDEN]'
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            await processor.processBatch([invocation])

            expect(mockFetch).toHaveBeenCalledTimes(0)

            expect(intercomPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(forSnapshot(getProducedKafkaMessagesForTopic('log_entries_test').map((m) => m.value.message)))
                .toMatchInlineSnapshot(`
                [
                  "Executing plugin posthog-intercom-plugin",
                  "Fetch called but mocked due to test function",
                  "Unable to search contact test@posthog.com in Intercom. Status Code: undefined. Error message: ",
                  "Execution successful",
                ]
            `)
        })

        it('should handle and collect errors', async () => {
            jest.spyOn(intercomPlugin as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockRejectedValue(new Error('Test error'))

            const res = await processor.processBatch([invocation])

            expect(intercomPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(res[0].error).toBeInstanceOf(Error)
            expect(forSnapshot(res[0].logs)).toMatchInlineSnapshot(`[]`)

            expect(forSnapshot(jest.mocked(processor['cyclotronWorker']!.updateJob).mock.calls)).toMatchInlineSnapshot(`
                [
                  [
                    "<REPLACED-UUID-0>",
                    "failed",
                  ],
                ]
            `)

            expect(forSnapshot(getProducedKafkaMessages())).toMatchSnapshot()
        })
    })

    describe('smoke tests', () => {
        const testCases = Object.entries(DESTINATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))

        it.each(testCases)('should run the plugin: %s', async ({ name, plugin }) => {
            globals.event.event = '$identify' // Many plugins filter for this
            const invocation = createInvocation(fn, globals)

            invocation.hogFunction.template_id = `plugin-${plugin.id}`

            const inputs: Record<string, any> = {}

            for (const input of plugin.metadata.config) {
                if (!input.key) {
                    continue
                }

                if (input.default) {
                    inputs[input.key] = input.default
                    continue
                }

                if (input.type === 'choice') {
                    inputs[input.key] = input.choices[0]
                } else if (input.type === 'string') {
                    inputs[input.key] = 'test'
                }
            }

            invocation.hogFunction.name = name
            await processor.processBatch([invocation])

            expect(
                forSnapshot(
                    getProducedKafkaMessagesForTopic('log_entries_test').map((m) => ({
                        message: m.value.message,
                        level: m.value.level,
                    }))
                )
            ).toMatchSnapshot()
        })
    })
})
