import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { createHogExecutionGlobals } from '../_tests/fixtures'
import { DESTINATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpLegacyEventsConsumer, LightweightPluginConfig } from './cdp-legacy-event.consumer'

jest.setTimeout(5000)

describe('CdpLegacyEventsConsumer', () => {
    let consumer: CdpLegacyEventsConsumer
    let legacyPluginExecutor: LegacyPluginExecutorService
    let hub: Hub
    let team: Team
    let pluginConfig: LightweightPluginConfig
    let invocation: HogFunctionInvocationGlobals
    let uniquePluginId: number

    const customerIoPlugin = DESTINATION_PLUGINS_BY_ID['plugin-customerio-plugin']

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        consumer = new CdpLegacyEventsConsumer(hub)
        legacyPluginExecutor = new LegacyPluginExecutorService(hub.postgres, hub.geoipService)
        team = await getFirstTeam(hub)

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        // Generate a unique plugin ID to avoid conflicts
        uniquePluginId = 50000 + Math.floor(Math.random() * 100000)

        // Create a plugin in the database with onEvent capability
        const { rows: pluginRows } = await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_plugin (id, organization_id, name, plugin_type, is_global, url, config_schema, from_json, from_web, created_at, updated_at, is_preinstalled, capabilities)
             VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13::jsonb)
             RETURNING *`,
            [
                uniquePluginId,
                team.organization_id,
                'Customer.io',
                'custom',
                false,
                'https://github.com/PostHog/customerio-plugin',
                JSON.stringify({}),
                false,
                false,
                new Date().toISOString(),
                new Date().toISOString(),
                false,
                JSON.stringify({ methods: ['onEvent'] }),
            ],
            'insertPlugin'
        )
        const plugin = pluginRows[0]

        // Create a plugin config with actual config values
        const pluginConfigData = {
            id: 10001,
            name: 'Customer.io Plugin',
            team_id: team.id,
            plugin_id: plugin.id,
            enabled: true,
            order: 0,
            config: {
                customerioSiteId: '1234567890',
                customerioToken: 'cio-token',
                email: 'test@posthog.com',
            },
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        }

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'INSERT INTO posthog_pluginconfig (id, team_id, plugin_id, enabled, "order", config, created_at, updated_at, deleted) VALUES ($1, $2, $3, true, $4, $5::jsonb, $6, $7, false)',
            [
                pluginConfigData.id,
                pluginConfigData.team_id,
                pluginConfigData.plugin_id,
                pluginConfigData.order,
                JSON.stringify(pluginConfigData.config),
                pluginConfigData.created_at,
                pluginConfigData.updated_at,
            ],
            'insertPluginConfig'
        )

        pluginConfig = pluginConfigData as any
        pluginConfig.plugin = plugin

        // Verify the plugin config was created with capability check
        const { rows } = await hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT
                posthog_pluginconfig.id,
                posthog_pluginconfig.team_id,
                posthog_plugin.capabilities
            FROM posthog_pluginconfig
            LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
            WHERE posthog_pluginconfig.id = $1
                AND posthog_pluginconfig.enabled = 't'
                AND (posthog_pluginconfig.deleted IS NULL OR posthog_pluginconfig.deleted != 't')
                AND posthog_plugin.capabilities->'methods' @> '["onEvent"]'::jsonb`,
            [pluginConfigData.id],
            'verifyPluginConfig'
        )
        expect(rows.length).toBe(1)

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

    describe('convertPluginConfigToHogFunction', () => {
        it('should convert a lightweight plugin config to a hog function', () => {
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

            const result = consumer['convertPluginConfigToHogFunction'](lightweightConfig)

            expect(result).toBeTruthy()
            expect(result?.template_id).toBe('plugin-customerio-plugin')
            expect(result?.type).toBe('destination')
            expect(result?.team_id).toBe(team.id)
            expect(result?.inputs).toMatchObject({
                customerioSiteId: { value: '1234567890' },
                customerioToken: { value: 'cio-token' },
                email: { value: 'test@posthog.com' },
                legacy_plugin_config_id: { value: pluginConfig.id },
            })
        })

        it('should include attachments in inputs when provided', () => {
            const lightweightConfig = {
                id: pluginConfig.id,
                team_id: team.id,
                plugin_id: pluginConfig.plugin_id,
                enabled: true,
                config: {
                    customerioSiteId: '1234567890',
                    customerioToken: 'cio-token',
                },
                created_at: '2025-01-01T00:00:00.000Z',
                updated_at: '2025-01-01T00:00:00.000Z',
                plugin: {
                    id: pluginConfig.plugin_id,
                    url: 'https://github.com/PostHog/customerio-plugin',
                },
            }

            const attachments = {
                mappings: {
                    event1: 'action1',
                    event2: 'action2',
                },
                customField: 'value123',
            }

            const result = consumer['convertPluginConfigToHogFunction'](lightweightConfig, attachments)

            expect(result).toBeTruthy()
            expect(result?.inputs).toMatchObject({
                customerioSiteId: { value: '1234567890' },
                customerioToken: { value: 'cio-token' },
                legacy_plugin_config_id: { value: pluginConfig.id },
                mappings: {
                    value: {
                        event1: 'action1',
                        event2: 'action2',
                    },
                },
                customField: { value: 'value123' },
            })
        })

        it('should not include attachments when config is empty', () => {
            const lightweightConfig = {
                id: pluginConfig.id,
                team_id: team.id,
                plugin_id: pluginConfig.plugin_id,
                enabled: true,
                config: {},
                created_at: '2025-01-01T00:00:00.000Z',
                updated_at: '2025-01-01T00:00:00.000Z',
                plugin: {
                    id: pluginConfig.plugin_id,
                    url: 'https://github.com/PostHog/customerio-plugin',
                },
            }

            const attachments = {
                mappings: {
                    event1: 'action1',
                },
            }

            const result = consumer['convertPluginConfigToHogFunction'](lightweightConfig, attachments)

            expect(result).toBeTruthy()
            expect(result?.inputs).toMatchObject({
                legacy_plugin_config_id: { value: pluginConfig.id },
            })
            expect(result?.inputs?.mappings).toBeUndefined()
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

            const result = consumer['convertPluginConfigToHogFunction'](lightweightConfig)

            expect(result?.template_id).toBe('plugin-semver-flattener')
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

            const result = consumer['convertPluginConfigToHogFunction'](lightweightConfig)

            expect(result).toBeNull()
        })
    })

    describe('getLegacyPluginHogFunctionInvocations', () => {
        it('should load hog functions and create invocations', async () => {
            // This test validates the full flow
            const invocations = await consumer['getLegacyPluginHogFunctionInvocations'](invocation)

            expect(invocations).toBeTruthy()
            expect(invocations.length).toBeGreaterThan(0)
            expect(invocations[0].hogFunction.template_id).toBe('plugin-customerio-plugin')

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

            const invocations = await consumer['getLegacyPluginHogFunctionInvocations'](emptyInvocation)
            expect(invocations).toEqual([])
        })

        it('should load attachments and include them in hog function inputs', async () => {
            // Insert an attachment for the plugin config
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_pluginattachment (id, plugin_config_id, key, contents, content_type, file_size, file_name)
                 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
                [
                    1001,
                    pluginConfig.id,
                    'mappings',
                    JSON.stringify({ event1: 'action1', event2: 'action2' }),
                    'application/json',
                    50,
                    'mappings.json',
                ],
                'insertPluginAttachment'
            )

            // Clear cache to force reload
            consumer['pluginConfigsLoader'].clear()

            // Get invocations
            const invocations = await consumer['getLegacyPluginHogFunctionInvocations'](invocation)

            expect(invocations).toBeTruthy()
            expect(invocations.length).toBeGreaterThan(0)

            // Check that the attachment was loaded into inputs
            const hogFunction = invocations[0].hogFunction
            expect(hogFunction.inputs).toBeTruthy()
            expect(hogFunction.inputs?.mappings).toBeTruthy()
            expect(hogFunction.inputs?.mappings?.value).toEqual({
                event1: 'action1',
                event2: 'action2',
            })

            // Verify other inputs are still present
            expect(hogFunction.inputs?.customerioSiteId?.value).toBe('1234567890')
            expect(hogFunction.inputs?.customerioToken?.value).toBe('cio-token')
        })
    })

    describe('integration with LegacyPluginExecutorService', () => {
        it('should create invocations that can be executed by the legacy plugin executor', async () => {
            jest.spyOn(customerIoPlugin, 'onEvent')

            // Execute the invocation with the legacy plugin executor
            invocation.event.event = '$identify'

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

            // Get invocations from the consumer - these are just logged, not executed
            const invocations = await consumer['getLegacyPluginHogFunctionInvocations'](invocation)
            expect(invocations).toBeTruthy()
            expect(invocations.length).toBeGreaterThan(0)

            const hogFunctionInvocation = invocations[0]
            expect(hogFunctionInvocation.hogFunction.template_id).toBe('plugin-customerio-plugin')

            // Verify the invocation structure is correct by executing it manually
            const result = await legacyPluginExecutor.execute(hogFunctionInvocation)

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

        it('should properly handle object attachments without converting them to "[object Object]"', async () => {
            // Insert an attachment with a complex object
            const attachmentObject = {
                event1: 'action1',
                event2: 'action2',
                nested: {
                    key: 'value',
                    array: [1, 2, 3],
                },
            }

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_pluginattachment (id, plugin_config_id, key, contents, content_type, file_size, file_name)
                 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
                [
                    2001,
                    pluginConfig.id,
                    'complexMapping',
                    JSON.stringify(attachmentObject),
                    'application/json',
                    100,
                    'complex-mapping.json',
                ],
                'insertComplexAttachment'
            )

            // Clear cache to force reload
            consumer['pluginConfigsLoader'].clear()

            // Get invocations
            const invocations = await consumer['getLegacyPluginHogFunctionInvocations'](invocation)

            expect(invocations).toBeTruthy()
            expect(invocations.length).toBeGreaterThan(0)

            // Verify that the inputs contain the actual object, not "[object Object]"
            const inputs = invocations[0].state.globals.inputs as Record<string, any>

            expect(inputs.complexMapping).toBeDefined()
            expect(typeof inputs.complexMapping).not.toBe('string')
            expect(inputs.complexMapping).toEqual(attachmentObject)

            // Verify it's not the string "[object Object]"
            expect(inputs.complexMapping).not.toBe('[object Object]')

            // Verify other string inputs are still strings
            expect(typeof inputs.customerioSiteId).toBe('string')
            expect(inputs.customerioSiteId).toBe('1234567890')
        })
    })

    describe('LazyLoader caching', () => {
        it('should cache hog functions and batch requests', async () => {
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
            const cachedHogFunctions = consumer['pluginConfigsLoader'].getCache()[team.id.toString()]
            expect(cachedHogFunctions).toBeTruthy()
            expect(cachedHogFunctions?.length).toBeGreaterThan(0)
            expect(cachedHogFunctions![0].hogFunction).toBeTruthy()
            expect(cachedHogFunctions![0].pluginConfigId).toBe(pluginConfig.id)
        })

        it('should return empty array for teams with no configs', async () => {
            const hogFunctions = await consumer['pluginConfigsLoader'].get('99999')
            expect(hogFunctions).toEqual([])
        })
    })

    describe('shutdown behavior', () => {
        it('should flush app metrics when stopping', async () => {
            const flushSpy = jest.spyOn(consumer['appMetrics'], 'flush')

            await consumer.stop()

            expect(flushSpy).toHaveBeenCalledTimes(1)
        })
    })
})
