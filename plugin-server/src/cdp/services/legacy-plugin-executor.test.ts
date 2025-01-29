import { DateTime } from 'luxon'

import {
    createHogExecutionGlobals,
    createHogFunction,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from '~/tests/cdp/fixtures'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { LegacyPluginExecutorService } from './legacy-plugin-executor.service'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('LegacyPluginExecutorService', () => {
    let service: LegacyPluginExecutorService
    let hub: Hub
    let team: Team
    let globals: HogFunctionInvocationGlobalsWithInputs
    let fn: HogFunctionType
    let mockFetch: jest.Mock

    const intercomPlugin = DESTINATION_PLUGINS_BY_ID['posthog-intercom-plugin']

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        service = new LegacyPluginExecutorService()
        team = await getFirstTeam(hub)

        fn = createHogFunction({
            name: 'Plugin test',
            template_id: `plugin-${intercomPlugin.id}`,
        })

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        mockFetch = jest.fn(() =>
            Promise.resolve({
                status: 200,
                json: () =>
                    Promise.resolve({
                        status: 200,
                    }),
            } as any)
        )

        jest.spyOn(service, 'fetch').mockImplementation(mockFetch)

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
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('setupPlugin', () => {
        it('should setup a plugin on first call', async () => {
            jest.spyOn(intercomPlugin, 'setupPlugin')

            await service.execute(createInvocation(fn, globals))

            const results = Promise.all([
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
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
            jest.spyOn(intercomPlugin, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
            })

            const res = await service.execute(invocation)

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
                    "team_id": 1,
                    "uuid": "uuid",
                  },
                  "properties": {
                    "email": "test@posthog.com",
                  },
                  "team_id": 1,
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

            expect(res.finished).toBe(true)
            expect(res.logs.map((l) => l.message)).toMatchInlineSnapshot(`
                [
                  "Executing plugin posthog-intercom-plugin",
                  "Contact test@posthog.com in Intercom found",
                  "Sent event mycustomevent for test@posthog.com to Intercom",
                  "Execution successful",
                ]
            `)
        })

        it('should mock out fetch if it is a test function', async () => {
            jest.spyOn(intercomPlugin, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.hogFunction.name = 'My function [CDP-TEST-HIDDEN]'
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            const res = await service.execute(invocation)

            expect(mockFetch).toHaveBeenCalledTimes(0)

            expect(intercomPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Executing plugin posthog-intercom-plugin",
                  "Fetch called but mocked due to test function",
                  "Unable to search contact test@posthog.com in Intercom. Status Code: undefined. Error message: ",
                  "Execution successful",
                ]
            `)
        })

        it('should handle and collect errors', async () => {
            jest.spyOn(intercomPlugin, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockRejectedValue(new Error('Test error'))

            const res = await service.execute(invocation)

            expect(intercomPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(res.error).toBeInstanceOf(Error)
            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Executing plugin posthog-intercom-plugin",
                  "Plugin execution failed: Service is down, retry later",
                ]
            `)

            expect(res.error).toEqual(new Error('Service is down, retry later'))
        })
    })

    describe('processEvent', () => {
        describe('mismatched types', () => {
            it('should throw if the plugin is a destination but the function is a transformation', async () => {
                fn.type = 'destination'
                fn.template_id = 'plugin-posthog-filter-out-plugin'

                const invocation = createInvocation(fn, globals)
                const res = await service.execute(invocation)

                expect(res.error).toMatchInlineSnapshot(
                    `[Error: Plugin posthog-filter-out-plugin is not a destination]`
                )
            })
        })
        describe('event dropping', () => {
            beforeEach(() => {
                fn.type = 'transformation'
                fn.template_id = 'plugin-posthog-filter-out-plugin'

                globals.inputs = {
                    eventsToDrop: 'drop-me',
                }
            })

            it('should not drop if event is returned', async () => {
                const invocation = createInvocation(fn, globals)
                invocation.globals.event.event = 'dont-drop-me'
                invocation.globals.event.properties = {
                    email: 'test@posthog.com',
                }

                const res = await service.execute(invocation)

                expect(res.finished).toBe(true)
                expect(res.error).toBeUndefined()
                expect(forSnapshot(res.execResult)).toMatchInlineSnapshot(`
                    {
                      "distinct_id": "distinct_id",
                      "event": "dont-drop-me",
                      "properties": {
                        "email": "test@posthog.com",
                      },
                      "team_id": 1,
                      "timestamp": "2025-01-01T00:00:00.000Z",
                      "uuid": "<REPLACED-UUID-0>",
                    }
                `)
            })

            it('should drop if event is dropped', async () => {
                const invocation = createInvocation(fn, globals)
                invocation.globals.event.event = 'drop-me'
                invocation.globals.event.properties = {
                    email: 'test@posthog.com',
                }

                const res = await service.execute(invocation)

                expect(res.finished).toBe(true)
                expect(res.error).toBeUndefined()
                expect(res.execResult).toBeUndefined()
            })
        })

        describe('event modification', () => {
            beforeEach(() => {
                fn.type = 'transformation'
                fn.template_id = 'plugin-semver-flattener-plugin'

                globals.inputs = {
                    properties: 'version',
                }
            })

            it('should modify the event', async () => {
                const invocation = createInvocation(fn, globals)
                invocation.globals.event.properties = {
                    version: '1.12.20',
                }

                const res = await service.execute(invocation)

                expect(res.finished).toBe(true)
                expect(res.error).toBeUndefined()
                expect(forSnapshot(res.execResult)).toMatchInlineSnapshot(`
                    {
                      "distinct_id": "distinct_id",
                      "event": "$pageview",
                      "properties": {
                        "version": "1.12.20",
                        "version__major": 1,
                        "version__minor": 12,
                        "version__patch": 20,
                      },
                      "team_id": 1,
                      "timestamp": "2025-01-01T00:00:00.000Z",
                      "uuid": "<REPLACED-UUID-0>",
                    }
                `)
            })
        })
    })

    describe('smoke tests', () => {
        const testCasesDestination = Object.entries(DESTINATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))

        it.each(testCasesDestination)('should run the destination plugin: %s', async ({ name, plugin }) => {
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
            const res = await service.execute(invocation)

            expect(res.logs.map((l) => l.message)).toMatchSnapshot()
        })

        const testCasesTransformation = Object.entries(TRANSFORMATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))

        it.each(testCasesTransformation)('should run the transformation plugin: %s', async ({ name, plugin }) => {
            globals.event.event = '$pageview'
            const invocation = createInvocation(fn, globals)

            invocation.hogFunction.type = 'transformation'
            invocation.hogFunction.template_id = `plugin-${plugin.id}`

            const inputs: Record<string, any> = {}

            for (const input of plugin.metadata.config || []) {
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
            invocation.globals.inputs = inputs
            const res = await service.execute(invocation)

            expect(res.logs.map((l) => l.message)).toMatchSnapshot()
        })
    })
})
