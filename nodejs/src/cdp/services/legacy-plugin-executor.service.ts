import { Counter, Histogram } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { GeoIPService, GeoIp } from '~/common/utils/geoip'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchOptions, FetchResponse } from '~/common/utils/request'
import { PluginEvent, ProcessedPluginEvent, RetryError, StorageExtension } from '~/plugin-scaffold'

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
import { CDP_TEST_ID, createAddLogFunction, destinationE2eLagMsSummary, isLegacyPluginHogFunction } from '../utils'
import { CdpFetchConfig, cdpTrackedFetch, getNextRetryTime } from '../utils/cdp-fetch'
import { createInvocationResult } from '../utils/invocation-utils'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_plugin_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

const setupPromiseCacheCounter = new Counter({
    name: 'cdp_plugin_setup_promise_cache_total',
    help: 'The number of times we have cached a setup promise',
    labelNames: ['result'],
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
    private pluginState: Record<string, PluginState> = {}
    private cachedGeoIp?: GeoIp

    constructor(
        private postgres: PostgresRouter,
        private geoipService: GeoIPService,
        // Only destination invocations run as cyclotron jobs, so only the consumers that execute
        // them supply the retry settings. Transformations run inline in ingestion.
        private fetchConfig?: CdpFetchConfig
    ) {}

    private legacyStorage(teamId: number, pluginConfigId?: number | string): Pick<StorageExtension, 'get' | 'set'> {
        if (!pluginConfigId) {
            return {
                get: () => Promise.resolve(null),
                set: () => Promise.resolve(),
            }
        }

        const get = async (key: string, defaultValue: unknown): Promise<unknown> => {
            const result = await this.postgres.query(
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
                const result = await this.postgres.query(
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

            await this.postgres.query(
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

    /**
     * A plugin raises RetryError for a failure a later attempt could clear, such as a 5xx or a
     * timeout. Put the invocation back on the cyclotron queue with the same capped backoff hog and
     * native destinations use, so a transient failure delays the event instead of dropping it.
     */
    private scheduleRetry(
        invocation: CyclotronJobInvocationHogFunction,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    ): boolean {
        if (!this.fetchConfig || invocation.hogFunction.type !== 'destination') {
            return false
        }

        const metadata = (invocation.queueMetadata as { tries: number }) || { tries: 0 }
        metadata.tries = metadata.tries + 1
        result.invocation.queueMetadata = metadata

        if (metadata.tries >= this.fetchConfig.CDP_FETCH_RETRIES) {
            return false
        }

        result.finished = false
        result.invocation.queue = 'hog'
        result.invocation.queuePriority = metadata.tries
        result.invocation.queueScheduledAt = getNextRetryTime(
            this.fetchConfig.CDP_FETCH_BACKOFF_BASE_MS,
            this.fetchConfig.CDP_FETCH_BACKOFF_MAX_MS,
            metadata.tries
        )

        return true
    }

    public async execute(
        invocation: CyclotronJobInvocationHogFunction,
        shouldMockFetch = false
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
                teamId: invocation.teamId,
                hogFunctionId: invocation.hogFunction.id,
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

            setupPromiseCacheCounter.labels({ result: state ? 'hit' : 'miss' }).inc()

            if (!state) {
                if (!this.cachedGeoIp) {
                    this.cachedGeoIp = await this.geoipService.get()
                }
                const geoip = this.cachedGeoIp

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

                if ((shouldMockFetch || isTestFunction) && method.toUpperCase() !== 'GET') {
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
                    // A destination plugin can mutate the properties it is given: the Customer.io plugin
                    // deletes `$set` and `$set_once` before it sends anything. The result carries the same
                    // globals object that goes back on the queue, so a retry must not see those edits.
                    properties: { ...event.properties } as ProcessedPluginEvent['properties'],
                    $set: event.$set as ProcessedPluginEvent['$set'],
                    $set_once: event.$set_once as ProcessedPluginEvent['$set_once'],
                }

                const start = performance.now()

                await plugin.onEvent?.(processedEvent, {
                    ...state.meta,
                    // NOTE: We override logger and fetch here so we can track the calls
                    logger: pluginLogger,
                    fetch: request,
                    // Not on state.meta because state is cached across invocations
                    person: globals.person,
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
                        this.legacyStorage(
                            invocation.hogFunction.team_id,
                            invocation.state.globals.inputs?.legacy_plugin_config_id
                        )
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
            if (result.finished) {
                const capturedAt = invocation.state.globals.event?.captured_at
                if (capturedAt) {
                    const e2eLagMs = Date.now() - new Date(capturedAt).getTime()
                    destinationE2eLagMsSummary.observe(e2eLagMs)
                }
            }
        } catch (e) {
            if (e instanceof RetryError && this.scheduleRetry(invocation, result)) {
                addLog('warn', `Plugin execution failed, retrying: ${e.message}`)
                return result
            }

            result.error = e

            addLog('error', `Plugin execution failed: ${e.message}`)
        }

        return result
    }
}
