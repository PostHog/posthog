import { DateTime } from 'luxon'

import {
    createHogExecutionGlobals,
    createHogFunction,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from '~/tests/cdp/fixtures'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { createPlugin, createPluginConfig } from '../../../tests/helpers/sql'
import { Hub, PluginConfig, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyDestinationPlugin, LegacyTransformationPlugin } from '../legacy-plugins/types'
import { HogFunctionInvocation, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
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
    let pluginConfig: PluginConfig

    const customerIoPlugin = DESTINATION_PLUGINS_BY_ID['plugin-customerio-plugin']

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        service = new LegacyPluginExecutorService(hub)
        team = await getFirstTeam(hub)

        fn = createHogFunction({
            name: 'Plugin test',
            template_id: customerIoPlugin.template.id,
            team_id: team.id,
        })

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        const plugin = await createPlugin(hub.postgres, {
            organization_id: team.organization_id,
            name: 'first-time-event-tracker',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
            export async function runEveryMinute() {
                console.info(JSON.stringify(['runEveryMinute']))
            }
        `,
        })
        pluginConfig = await createPluginConfig(hub.postgres, {
            id: 10001,
            name: 'first-time-event-tracker',
            team_id: team.id,
            plugin_id: plugin.id,
        } as any)

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
                customerioSiteId: '1234567890',
                customerioToken: 'cio-token',
                email: 'test@posthog.com',
                legacy_plugin_config_id: pluginConfig.id,
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
            jest.spyOn(customerIoPlugin, 'setupPlugin')

            await service.execute(createInvocation(fn, globals))

            const results = Promise.all([
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
            ])

            expect(service['pluginState'][fn.id]).toBeDefined()

            expect(await results).toMatchObject([{ finished: true }, { finished: true }, { finished: true }])

            expect(customerIoPlugin.setupPlugin).toHaveBeenCalledTimes(1)
            expect(jest.mocked(customerIoPlugin.setupPlugin!).mock.calls[0][0]).toMatchObject({
                config: {
                    customerioSiteId: '1234567890',
                    customerioToken: 'cio-token',
                    email: 'test@posthog.com',
                },
                geoip: {
                    locate: expect.any(Function),
                },
                global: {
                    authorizationHeader: 'Basic MTIzNDU2Nzg5MDpjaW8tdG9rZW4=',
                    eventNames: [],
                    eventsConfig: '1',
                    identifyByEmail: false,
                },
                logger: {
                    debug: expect.any(Function),
                    error: expect.any(Function),
                    log: expect.any(Function),
                    warn: expect.any(Function),
                },
            })
        })
    })

    describe('onEvent', () => {
        it('should call the plugin onEvent method', async () => {
            jest.spyOn(customerIoPlugin, 'onEvent')

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

            expect(res.finished).toBe(true)
            expect(res.error).toBeUndefined()

            expect(customerIoPlugin.onEvent).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(customerIoPlugin.onEvent!).mock.calls[0][0])).toMatchInlineSnapshot(`
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

            // One for setup and then two calls
            expect(mockFetch).toHaveBeenCalledTimes(3)
            expect(forSnapshot(mockFetch.mock.calls)).toMatchInlineSnapshot(`
                [
                  [
                    "https://api.customer.io/v1/api/info/ip_addresses",
                    {
                      "headers": {
                        "Authorization": "Basic MTIzNDU2Nzg5MDpjaW8tdG9rZW4=",
                        "User-Agent": "PostHog Customer.io App",
                      },
                      "method": "GET",
                    },
                  ],
                  [
                    "https://track.customer.io/api/v1/customers/distinct_id",
                    {
                      "body": "{"_update":false,"identifier":"distinct_id","email":"test@posthog.com"}",
                      "headers": {
                        "Authorization": "Basic MTIzNDU2Nzg5MDpjaW8tdG9rZW4=",
                        "Content-Type": "application/json",
                        "User-Agent": "PostHog Customer.io App",
                      },
                      "method": "PUT",
                    },
                  ],
                  [
                    "https://track.customer.io/api/v1/customers/distinct_id/events",
                    {
                      "body": "{"name":"mycustomevent","type":"event","timestamp":1735689600,"data":{"email":"test@posthog.com"}}",
                      "headers": {
                        "Authorization": "Basic MTIzNDU2Nzg5MDpjaW8tdG9rZW4=",
                        "Content-Type": "application/json",
                        "User-Agent": "PostHog Customer.io App",
                      },
                      "method": "POST",
                    },
                  ],
                ]
            `)

            expect(res.finished).toBe(true)
            expect(res.logs.map((l) => l.message)).toMatchInlineSnapshot(`
                [
                  "Successfully authenticated with Customer.io. Completing setupPlugin.",
                  "Detected email, test@posthog.com",
                  "{"status":{},"existsAlready":false,"email":"test@posthog.com"}",
                  "true",
                ]
            `)
        })

        it('should mock out fetch if it is a test function', async () => {
            jest.spyOn(customerIoPlugin, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.hogFunction.name = 'My function [CDP-TEST-HIDDEN]'
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            const res = await service.execute(invocation)

            // NOTE: Setup call is not mocked
            expect(mockFetch).toHaveBeenCalledTimes(1)

            expect(customerIoPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Successfully authenticated with Customer.io. Completing setupPlugin.",
                  "Detected email, test@posthog.com",
                  "{"status":{},"existsAlready":false,"email":"test@posthog.com"}",
                  "true",
                  "Fetch called but mocked due to test function",
                  "Fetch called but mocked due to test function",
                ]
            `)
        })

        it('should handle and collect errors', async () => {
            jest.spyOn(customerIoPlugin, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            // First fetch is successful (setup)
            // Second one not

            mockFetch.mockImplementation((url) => {
                if (url.includes('customers')) {
                    return Promise.resolve({ status: 500, json: () => Promise.resolve({}) })
                }

                return Promise.resolve({ status: 200 })
            })

            const res = await service.execute(invocation)

            expect(customerIoPlugin.onEvent).toHaveBeenCalledTimes(1)

            expect(res.error).toBeInstanceOf(Error)
            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Successfully authenticated with Customer.io. Completing setupPlugin.",
                  "Detected email, test@posthog.com",
                  "{"status":{},"existsAlready":false,"email":"test@posthog.com"}",
                  "true",
                  "Plugin execution failed: Received a potentially intermittent error from the Customer.io API. Response 500: {}",
                ]
            `)

            expect(res.error).toMatchInlineSnapshot(
                `[RetryError: Received a potentially intermittent error from the Customer.io API. Response 500: {}]`
            )
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
                    `[Error: Plugin plugin-posthog-filter-out-plugin is not a destination]`
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
                      "team_id": 2,
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
                      "team_id": 2,
                      "timestamp": "2025-01-01T00:00:00.000Z",
                      "uuid": "<REPLACED-UUID-0>",
                    }
                `)
            })
        })
    })

    describe('smoke tests', () => {
        const buildInvocation = (
            plugin: LegacyDestinationPlugin | LegacyTransformationPlugin
        ): HogFunctionInvocation => {
            const invocation = createInvocation(fn, globals)
            invocation.globals.inputs = {}
            invocation.hogFunction.template_id = plugin.template.id

            const inputs: Record<string, any> = {}

            for (const input of plugin.template.inputs_schema) {
                if (!input.key) {
                    continue
                }

                if (input.default) {
                    inputs[input.key] = input.default
                    continue
                }

                if (input.type === 'choice') {
                    inputs[input.key] = input.choices?.[0].value
                } else if (input.type === 'string') {
                    inputs[input.key] = 'test'
                }
            }

            invocation.globals.inputs = inputs
            return invocation
        }
        const testCasesDestination = Object.entries(DESTINATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))
        it.each(testCasesDestination)('should run the destination plugin: %s', async ({ name, plugin }) => {
            const invocation = buildInvocation(plugin)
            invocation.hogFunction.name = name
            invocation.globals.event.event = '$identify' // Many plugins filter for this

            if (plugin.template.id === 'plugin-customerio-plugin') {
                invocation.globals.inputs.legacy_plugin_config_id = pluginConfig.id
            }
            const res = await service.execute(invocation)
            expect(res.logs.map((l) => l.message)).toMatchSnapshot()
        })

        const testCasesTransformation = Object.entries(TRANSFORMATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))

        it.each(testCasesTransformation)('should run the transformation plugin: %s', async ({ name, plugin }) => {
            const invocation = buildInvocation(plugin)
            invocation.hogFunction.name = name
            invocation.hogFunction.type = 'transformation'
            invocation.globals.event.event = '$pageview'
            const res = await service.execute(invocation)
            expect(res.logs.map((l) => l.message)).toMatchSnapshot()
        })
    })

    describe('first-time-event-tracker', () => {
        let invocation: HogFunctionInvocation
        beforeEach(() => {
            fn = createHogFunction({
                team_id: team.id,
                name: 'First time event tracker',
                template_id: 'plugin-first-time-event-tracker',
                type: 'transformation',
            })

            globals.inputs = {
                events: '$pageview',
                legacy_plugin_config_id: '123',
            }
            invocation = createInvocation(fn, globals)
        })

        it('should error if no legacy plugin config id is provided', async () => {
            const res = await service.execute(invocation)

            expect(res.finished).toBe(true)
            expect(res.error).toMatchInlineSnapshot(`[Error: Plugin config 123 for team 2 not found]`)
        })

        it('should succeed if legacy plugin config id is provided', async () => {
            invocation.globals.inputs.legacy_plugin_config_id = pluginConfig.id

            const res = await service.execute(invocation)

            expect(res.finished).toBe(true)
            expect(res.error).toBeUndefined()
        })
    })
})
