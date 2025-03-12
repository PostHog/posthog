import { PluginEvent, ProcessedPluginEvent, RetryError, StorageExtension } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { Hub } from '~/src/types'

import { PostgresUse } from '../../utils/db/postgres'
import { Response, trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { firstTimeEventTrackerPluginProcessEventAsync } from '../legacy-plugins/_transformations/first-time-event-tracker'
import { firstTimeEventTrackerPlugin } from '../legacy-plugins/_transformations/first-time-event-tracker/template'
import {
    LegacyDestinationPlugin,
    LegacyPluginLogger,
    LegacyTransformationPlugin,
    LegacyTransformationPluginMeta,
} from '../legacy-plugins/types'
import { sanitizeLogMessage } from '../services/hog-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult } from '../types'
import { isLegacyPluginHogFunction } from '../utils'

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

export type LegacyPluginExecutorOptions = {
    fetch?: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export class LegacyPluginExecutorService {
    constructor(private hub: Hub) {}
    private pluginState: Record<string, PluginState> = {}

    public async fetch(...args: Parameters<typeof trackedFetch>): Promise<Response> {
        return trackedFetch(...args)
    }

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

            return result?.rows.length === 1 ? JSON.parse(result.rows[0].value) : defaultValue
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
        invocation: HogFunctionInvocation,
        options?: LegacyPluginExecutorOptions
    ): Promise<HogFunctionInvocationResult> {
        const fetch = options?.fetch || this.fetch

        const result: HogFunctionInvocationResult = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
        }

        const addLog = (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
            result.logs.push({
                level,
                timestamp: DateTime.now(),
                message: sanitizeLogMessage(args),
            })
        }

        const logger: LegacyPluginLogger = {
            debug: (...args: any[]) => addLog('debug', ...args),
            warn: (...args: any[]) => addLog('warn', ...args),
            log: (...args: any[]) => addLog('info', ...args),
            error: (...args: any[]) => addLog('error', ...args),
        }

        const pluginId = isLegacyPluginHogFunction(invocation.hogFunction) ? invocation.hogFunction.template_id : null

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
            const legacyPluginConfigId = invocation.globals.inputs?.legacy_plugin_config_id

            if (!state) {
                const geoip = await this.hub.geoipService.get()

                const meta: LegacyTransformationPluginMeta = {
                    config: invocation.globals.inputs,
                    global: {},
                    logger: logger,
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
                            fetch: this.fetch,
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

            const start = performance.now()

            const person: ProcessedPluginEvent['person'] = invocation.globals.person
                ? {
                      uuid: invocation.globals.person.id,
                      team_id: invocation.hogFunction.team_id,
                      properties: invocation.globals.person.properties,
                      created_at: '', // NOTE: We don't have this anymore - see if any plugin uses it...
                  }
                : undefined

            const event = {
                distinct_id: invocation.globals.event.distinct_id,
                ip: invocation.globals.event.properties.$ip,
                team_id: invocation.hogFunction.team_id,
                event: invocation.globals.event.event,
                properties: invocation.globals.event.properties,
                timestamp: invocation.globals.event.timestamp,
                $set: invocation.globals.event.properties.$set,
                $set_once: invocation.globals.event.properties.$set_once,
                uuid: invocation.globals.event.uuid,
            }

            if ('onEvent' in plugin) {
                // Destination style
                const processedEvent: ProcessedPluginEvent = {
                    ...event,
                    person,
                    properties: event.properties || {},
                }

                await plugin.onEvent?.(processedEvent, {
                    ...state.meta,
                    // NOTE: We override logger and fetch here so we can track the calls
                    logger,
                    fetch,
                    storage: this.legacyStorage(invocation.hogFunction.team_id, legacyPluginConfigId),
                })
            } else {
                if (plugin === firstTimeEventTrackerPlugin) {
                    // Special fallback case until this is fully removed
                    const transformedEvent = await firstTimeEventTrackerPluginProcessEventAsync(
                        event as PluginEvent,
                        {
                            ...state.meta,
                            logger,
                        },
                        this.legacyStorage(invocation.hogFunction.team_id, legacyPluginConfigId)
                    )
                    result.execResult = transformedEvent
                } else {
                    // Transformation style
                    const transformedEvent = plugin.processEvent(event as PluginEvent, {
                        ...state.meta,
                        logger,
                    })
                    result.execResult = transformedEvent
                }
            }

            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }

            status.error('💩', 'Plugin errored', {
                error: e.message,
                pluginId,
                invocationId: invocation.id,
            })

            result.error = e

            addLog('error', `Plugin execution failed: ${e.message}`)
        }

        return result
    }
}
