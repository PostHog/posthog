import { Histogram } from 'prom-client'

import { PluginEvent, ProcessedPluginEvent, RetryError, StorageExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { FetchOptions, FetchResponse } from '../../utils/request'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { firstTimeEventTrackerPluginProcessEventAsync } from '../legacy-plugins/_transformations/first-time-event-tracker'
import { firstTimeEventTrackerPlugin } from '../legacy-plugins/_transformations/first-time-event-tracker/template'
import {
    LegacyDestinationPlugin,
    LegacyPluginLogger,
    LegacyTransformationPlugin,
    LegacyTransformationPluginMeta,
} from '../legacy-plugins/types'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { CDP_TEST_ID, createAddLogFunction, isLegacyPluginHogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { cdpTrackedFetch } from './hog-executor.service'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_plugin_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

export type PluginState = {
    setupPromise: Promise<any>
    errored: boolean
    meta: LegacyTransformationPluginMeta
}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */

const pluginConfigCheckCache: Record<string, boolean> = {}

export class LegacyPluginExecutorService {
    constructor(private hub: Hub) {}
    private pluginState: Record<string, PluginState> = {}

    private legacyStorage(teamId: number, pluginConfigId?: number | string): Pick<StorageExtension, 'get' | 'set'> {
        if (!pluginConfigId) {
            return {
                get: () => Promise.resolve(null),
                set: () => Promise.resolve(),
            }
        }

        const get = async (key: string, defaultValue: unknown): Promise<unknown> => {
            const result = await this.hub.db.postgres.query(
                PostgresUse.PLUGIN_STORAGE_RW,
                `SELECT * FROM posthog_pluginstorage as ps 
                   JOIN posthog_pluginconfig as pc ON ps."plugin_config_id" = pc."id" 
                   WHERE pc."team_id" = $1 AND pc."id" = $2 AND ps."key" = $3
                   LIMIT 1`,
                [teamId, pluginConfigId, key],
                'storageGet'
            )

            return result?.rows.length === 1 ? parseJSON(result.rows[0].value) : defaultValue
        }
        const set = async (key: string, value: unknown): Promise<void> => {
            const cacheKey = `${teamId}-${pluginConfigId}`

            if (typeof pluginConfigCheckCache[cacheKey] === 'undefined') {
                // Check if the plugin config for that team exists
                const result = await this.hub.db.postgres.query(
                    PostgresUse.COMMON_READ,
                    `SELECT * FROM posthog_pluginconfig as pc 
                   WHERE pc."team_id" = $1 AND pc."id" = $2
                   LIMIT 1`,
                    [teamId, pluginConfigId],
                    'storageGet'
                )

                pluginConfigCheckCache[cacheKey] = result?.rows.length === 1
            }

            if (!pluginConfigCheckCache[cacheKey]) {
                throw new Error(`Plugin config ${pluginConfigId} for team ${teamId} not found`)
            }

            await this.hub.db.postgres.query(
                PostgresUse.PLUGIN_STORAGE_RW,
                `
                    INSERT INTO posthog_pluginstorage ("plugin_config_id", "key", "value")
                    VALUES ($1, $2, $3)
                    ON CONFLICT ("plugin_config_id", "key")
                    DO UPDATE SET value = $3
                `,
                [pluginConfigId, key, JSON.stringify(value)],
                `storageSet`
            )
        }

        return {
            get,
            set,
        }
    }

    public async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)
        const addLog = createAddLogFunction(result.logs)

        const pluginLogger: LegacyPluginLogger = {
            debug: (...args: any[]) => addLog('debug', ...args),
            warn: (...args: any[]) => addLog('warn', ...args),
            log: (...args: any[]) => addLog('info', ...args),
            error: (...args: any[]) => addLog('error', ...args),
        }

        const pluginId = isLegacyPluginHogFunction(invocation.hogFunction) ? invocation.hogFunction.template_id : null

        const fetch = async (url: string, fetchParams: FetchOptions): Promise<FetchResponse> => {
            const { fetchError, fetchResponse } = await cdpTrackedFetch({
                url,
                fetchParams,
                templateId: invocation.hogFunction.template_id ?? '',
            })

            if (fetchError || !fetchResponse) {
                throw fetchError ?? new Error('Fetch response is null')
            }

            return fetchResponse
        }

        try {
            const plugin = pluginId
                ? ((DESTINATION_PLUGINS_BY_ID[pluginId] || TRANSFORMATION_PLUGINS_BY_ID[pluginId]) as
                      | LegacyTransformationPlugin
                      | LegacyDestinationPlugin)
                : null

            if (!pluginId || !plugin) {
                throw new Error(`Plugin ${pluginId} not found`)
            }

            if (invocation.hogFunction.type === 'destination' && 'processEvent' in plugin) {
                throw new Error(`Plugin ${pluginId} is not a destination`)
            } else if (invocation.hogFunction.type === 'transformation' && 'onEvent' in plugin) {
                throw new Error(`Plugin ${pluginId} is not a transformation`)
            }

            let state = this.pluginState[invocation.hogFunction.id]

            // NOTE: If this is set then we can add in the legacy storage
            const legacyPluginConfigId = invocation.state.globals.inputs?.legacy_plugin_config_id

            if (!state) {
                const geoip = await this.hub.geoipService.get()

                const meta: LegacyTransformationPluginMeta = {
                    config: invocation.state.globals.inputs,
                    global: {},
                    logger: pluginLogger,
                    geoip: {
                        locate: (ipAddress: string): Record<string, any> | null => {
                            try {
                                return geoip.city(ipAddress)
                            } catch {
                                return null
                            }
                        },
                    },
                }

                let setupPromise = Promise.resolve()

                if (plugin.setupPlugin) {
                    if ('processEvent' in plugin) {
                        // Transformation plugin takes basic meta and isn't async
                        setupPromise = Promise.resolve(plugin.setupPlugin(meta))
                    } else {
                        // Destination plugin can use fetch and is async
                        setupPromise = plugin.setupPlugin({
                            ...meta,
                            // Setup receives the real fetch always
                            fetch,
                            storage: this.legacyStorage(invocation.hogFunction.team_id, legacyPluginConfigId),
                        })
                    }
                }

                state = this.pluginState[invocation.hogFunction.id] = {
                    setupPromise,
                    meta,
                    errored: false,
                }
            }

            try {
                await state.setupPromise
            } catch (e) {
                throw new Error(`Plugin ${pluginId} setup failed: ${e.message}`)
            }

            const isTestFunction = invocation.hogFunction.name.includes(CDP_TEST_ID)

            const request = async (...args: Parameters<typeof fetch>) => {
                // TRICKY: We use the overridden fetch here if given as it is used by the comparer service
                // Additionally we don't do real fetches for test functions
                const method = args[1] && typeof args[1].method === 'string' ? args[1].method : 'GET'

                if (isTestFunction && method.toUpperCase() !== 'GET') {
                    // For testing we mock out all non-GET requests
                    addLog('info', 'Fetch called but mocked due to test function', {
                        url: args[0],
                        method,
                    })

                    result.metrics!.push({
                        team_id: invocation.hogFunction.team_id,
                        app_source_id: invocation.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    })
                    // Simulate a mini bit of fetch delay
                    await new Promise((resolve) => setTimeout(resolve, 200))
                    return {
                        status: 200,
                        headers: {},
                        json: () =>
                            Promise.resolve({
                                status: 'OK',
                                message: 'Test function',
                            }),
                        text: () =>
                            Promise.resolve(
                                JSON.stringify({
                                    status: 'OK',
                                    message: 'Test function',
                                })
                            ),
                    } as FetchResponse
                }

                return fetch(...args)
            }

            const start = performance.now()
            const globals = invocation.state.globals

            const event = {
                distinct_id: globals.event.distinct_id,
                ip: globals.event.properties.$ip,
                team_id: invocation.hogFunction.team_id,
                event: globals.event.event,
                properties: globals.event.properties,
                timestamp: globals.event.timestamp,
                $set: globals.event.properties.$set,
                $set_once: globals.event.properties.$set_once,
                uuid: globals.event.uuid,
            }

            if ('onEvent' in plugin) {
                // Destination style
                const processedEvent: ProcessedPluginEvent = {
                    ...event,
                    ip: null, // convertToOnEventPayload removes this so we should too
                    // NOTE: We want to improve validation of these properties but for now for legacy plugins we just cast
                    properties: event.properties as ProcessedPluginEvent['properties'],
                    $set: event.$set as ProcessedPluginEvent['$set'],
                    $set_once: event.$set_once as ProcessedPluginEvent['$set_once'],
                }

                const start = performance.now()

                await plugin.onEvent?.(processedEvent, {
                    ...state.meta,
                    // NOTE: We override logger and fetch here so we can track the calls
                    logger: pluginLogger,
                    fetch: request,
                    storage: this.legacyStorage(invocation.hogFunction.team_id, legacyPluginConfigId),
                })

                addLog('info', `Function completed in ${performance.now() - start}ms.`)
            } else {
                if (plugin === firstTimeEventTrackerPlugin) {
                    // Special fallback case until this is fully removed
                    const transformedEvent = await firstTimeEventTrackerPluginProcessEventAsync(
                        event as PluginEvent,
                        {
                            ...state.meta,
                            logger: pluginLogger,
                        },
                        this.legacyStorage(invocation.hogFunction.team_id, legacyPluginConfigId)
                    )
                    result.execResult = transformedEvent
                } else {
                    // Transformation style
                    const transformedEvent = plugin.processEvent(event as PluginEvent, {
                        ...state.meta,
                        logger: pluginLogger,
                    })
                    result.execResult = transformedEvent
                }
            }

            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }

            result.error = e

            addLog('error', `Plugin execution failed: ${e.message}`)
        }

        return result
    }
}
