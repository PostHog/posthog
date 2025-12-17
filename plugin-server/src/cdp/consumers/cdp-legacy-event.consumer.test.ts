import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { createPlugin, createPluginConfig } from '../../../tests/helpers/sql'
import { Hub, PluginConfig, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createHogExecutionGlobals } from '../_tests/fixtures'
import { DESTINATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpLegacyEventsConsumer } from './cdp-legacy-event.consumer'

jest.setTimeout(5000)

describe('CdpLegacyEventsConsumer', () => {
    let consumer: CdpLegacyEventsConsumer
    let legacyPluginExecutor: LegacyPluginExecutorService
    let hub: Hub
    let team: Team
    let pluginConfig: PluginConfig
    let invocation: HogFunctionInvocationGlobals

    const customerIoPlugin = DESTINATION_PLUGINS_BY_ID['plugin-customerio-plugin']

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        consumer = new CdpLegacyEventsConsumer(hub)
        legacyPluginExecutor = new LegacyPluginExecutorService(hub)
        team = await getFirstTeam(hub)

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        // Create a plugin in the database
        const plugin = await createPlugin(hub.postgres, {
            organization_id: team.organization_id,
            name: 'Customer.io',
            plugin_type: 'custom',
            is_global: false,
            url: 'https://github.com/PostHog/customerio-plugin',
        })

        // Create a plugin config
        pluginConfig = await createPluginConfig(hub.postgres, {
            id: 10001,
            name: 'Customer.io Plugin',
            team_id: team.id,
            plugin_id: plugin.id,
            enabled: true,
            config: {
                customerioSiteId: '1234567890',
                customerioToken: 'cio-token',
                email: 'test@posthog.com',
            },
        } as any)

        mockFetch.mockImplementation((_url, _options) =>
            Promise.resolve({
                status: 200,
                json: () =>
                    Promise.resolve({
                        status: 200,
                    }),
                text: () =>
                    Promise.resolve(
                        JSON.stringify({
                            status: 200,
                        })
                    ),
                headers: {},
                dump: () => Promise.resolve(),
            })
        )

        invocation = createHogExecutionGlobals({
            project: {
                id: team.id,
                name: team.name,
                url: `http://localhost:8000/projects/${team.id}`,
            } as any,
            event: {
                uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                event: '$pageview',
                distinct_id: 'distinct_id',
                properties: {
                    $current_url: 'https://posthog.com',
                    $lib_version: '1.0.0',
                },
                timestamp: fixedTime.toISO(),
                url: 'http://localhost:8000/events/event_id',
            } as any,
        })
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('convertPluginConfigToHogFunctionInvocation', () => {
        it('should convert a lightweight plugin config to a hog function invocation', () => {
            const lightweightConfig = {
                id: pluginConfig.id,
                team_id: team.id,
                plugin_id: pluginConfig.plugin_id,
                enabled: true,
                config: {
                    customerioSiteId: '1234567890',
                    customerioToken: 'cio-token',
                    email: 'test@posthog.com',
                },
                created_at: '2025-01-01T00:00:00.000Z',
                updated_at: '2025-01-01T00:00:00.000Z',
                plugin: {
                    id: pluginConfig.plugin_id,
                    url: 'https://github.com/PostHog/customerio-plugin',
                },
            }

            const result = consumer['convertPluginConfigToHogFunctionInvocation'](lightweightConfig, invocation)

            expect(result).toBeTruthy()
            expect(result?.hogFunction.template_id).toBe('plugin-customerio-plugin')
            expect(result?.hogFunction.type).toBe('destination')
            expect(result?.hogFunction.team_id).toBe(team.id)
            expect(result?.state.globals.inputs).toMatchObject({
                customerioSiteId: '1234567890',
                customerioToken: 'cio-token',
                email: 'test@posthog.com',
                legacy_plugin_config_id: pluginConfig.id,
            })
        })

        it('should handle inline plugin URLs correctly', () => {
            const lightweightConfig = {
                id: 1,
                team_id: team.id,
                plugin_id: 1,
                enabled: true,
                config: {
                    properties: 'version',
                },
                created_at: '2025-01-01T00:00:00.000Z',
                plugin: {
                    id: 1,
                    url: 'inline://semver-flattener',
                },
            }

            const result = consumer['convertPluginConfigToHogFunctionInvocation'](lightweightConfig, invocation)

            expect(result?.hogFunction.template_id).toBe('plugin-semver-flattener-plugin')
        })

        it('should return null if plugin has no URL', () => {
            const lightweightConfig = {
                id: 1,
                team_id: team.id,
                plugin_id: 1,
                enabled: true,
                config: {},
                created_at: '2025-01-01T00:00:00.000Z',
            }

            const result = consumer['convertPluginConfigToHogFunctionInvocation'](lightweightConfig, invocation)

            expect(result).toBeNull()
        })
    })

    describe('comparePluginConfigsToLightweightPluginConfigs', () => {
        it('should load lightweight configs and convert them to hog function invocations', async () => {
            // This test validates the full flow
            await consumer['comparePluginConfigsToLightweightPluginConfigs'](invocation, [])

            // Check that the loader was called and cached
            const cachedConfigs = consumer['pluginConfigsLoader'].getCache()[team.id.toString()]
            expect(cachedConfigs).toBeTruthy()
            expect(cachedConfigs?.length).toBeGreaterThan(0)
        })

        it('should handle teams with no plugin configs', async () => {
            // Create invocation for a team that doesn't exist
            const emptyInvocation = {
                ...invocation,
                project: {
                    ...invocation.project,
                    id: 99999,
                },
            }

            await expect(
                consumer['comparePluginConfigsToLightweightPluginConfigs'](emptyInvocation, [])
            ).resolves.not.toThrow()
        })
    })

    describe('integration with LegacyPluginExecutorService', () => {
        it('should create invocations that can be executed by the legacy plugin executor', async () => {
            jest.spyOn(customerIoPlugin, 'onEvent')

            // Get the lightweight plugin config
            const lightweightConfigs = await consumer['pluginConfigsLoader'].get(team.id.toString())
            expect(lightweightConfigs).toBeTruthy()
            expect(lightweightConfigs?.length).toBeGreaterThan(0)

            const lightweightConfig = lightweightConfigs![0]

            // Manually construct a config with the correct URL for testing
            const testConfig = {
                ...lightweightConfig,
                plugin: {
                    id: lightweightConfig.plugin_id,
                    url: 'https://github.com/PostHog/customerio-plugin',
                },
            }

            const hogFunctionInvocation = consumer['convertPluginConfigToHogFunctionInvocation'](testConfig, invocation)

            expect(hogFunctionInvocation).toBeTruthy()
            expect(hogFunctionInvocation?.hogFunction.template_id).toBe('plugin-customerio-plugin')

            // Execute the invocation with the legacy plugin executor
            invocation.event.event = '$identify'
            hogFunctionInvocation!.state.globals.event.event = '$identify'

            mockFetch.mockResolvedValue({
                status: 200,
                json: () =>
                    Promise.resolve({
                        total_count: 1,
                    }),
                text: () =>
                    Promise.resolve(
                        JSON.stringify({
                            total_count: 1,
                        })
                    ),
                headers: {},
                dump: () => Promise.resolve(),
            })

            const result = await legacyPluginExecutor.execute(hogFunctionInvocation!)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            expect(customerIoPlugin.onEvent).toHaveBeenCalledTimes(1)

            // Verify the event passed to the plugin
            expect(forSnapshot(jest.mocked(customerIoPlugin.onEvent!).mock.calls[0][0])).toMatchInlineSnapshot(`
                {
                  "$set": undefined,
                  "$set_once": undefined,
                  "distinct_id": "distinct_id",
                  "event": "$identify",
                  "ip": null,
                  "properties": {
                    "$current_url": "https://posthog.com",
                    "$lib_version": "1.0.0",
                  },
                  "team_id": 2,
                  "timestamp": "2025-01-01T00:00:00.000Z",
                  "uuid": "<REPLACED-UUID-0>",
                }
            `)

            // Verify fetch was called (setup + 2 calls from onEvent)
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })
    })

    describe('LazyLoader caching', () => {
        it('should cache plugin configs and batch requests', async () => {
            // Clear any existing cache
            consumer['pluginConfigsLoader'].clear()

            // Make multiple requests in parallel
            const results = await Promise.all([
                consumer['pluginConfigsLoader'].get(team.id.toString()),
                consumer['pluginConfigsLoader'].get(team.id.toString()),
                consumer['pluginConfigsLoader'].get(team.id.toString()),
            ])

            // All should return the same result
            expect(results[0]).toEqual(results[1])
            expect(results[1]).toEqual(results[2])

            // Check cache is populated
            const cachedConfigs = consumer['pluginConfigsLoader'].getCache()[team.id.toString()]
            expect(cachedConfigs).toBeTruthy()
            expect(cachedConfigs?.length).toBeGreaterThan(0)
        })

        it('should return empty array for teams with no configs', async () => {
            const configs = await consumer['pluginConfigsLoader'].get('99999')
            expect(configs).toEqual([])
        })
    })
})
