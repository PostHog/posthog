import { PluginEvent, ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { Response, trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
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
export class LegacyPluginExecutorService {
    private pluginState: Record<string, PluginState> = {}

    public async fetch(...args: Parameters<typeof trackedFetch>): Promise<Response> {
        return trackedFetch(...args)
    }

    public async execute(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        const result: HogFunctionInvocationResult = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
        }

        const isTestFunction = invocation.hogFunction.name.includes('[CDP-TEST-HIDDEN]')

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

        const fetch = (...args: Parameters<typeof trackedFetch>): Promise<Response> => {
            if (isTestFunction) {
                addLog('info', 'Fetch called but mocked due to test function')
                return Promise.resolve({
                    status: 500,
                    json: () =>
                        Promise.resolve({
                            message: 'Test function',
                        }),
                } as Response)
            }
            return this.fetch(...args)
        }

        const pluginId = isLegacyPluginHogFunction(invocation.hogFunction)
            ? invocation.hogFunction.template_id?.replace('plugin-', '')
            : null

        try {
            const plugin = pluginId
                ? ((DESTINATION_PLUGINS_BY_ID[pluginId] || TRANSFORMATION_PLUGINS_BY_ID[pluginId]) as
                      | LegacyTransformationPlugin
                      | LegacyDestinationPlugin)
                : null

            addLog('debug', `Executing plugin ${pluginId}`)

            if (!pluginId || !plugin) {
                throw new Error(`Plugin ${pluginId} not found`)
            }

            if (invocation.hogFunction.type === 'destination' && 'processEvent' in plugin) {
                throw new Error(`Plugin ${pluginId} is not a destination`)
            } else if (invocation.hogFunction.type === 'transformation' && 'onEvent' in plugin) {
                throw new Error(`Plugin ${pluginId} is not a transformation`)
            }

            let state = this.pluginState[pluginId]

            if (!state) {
                // TODO: Modify fetch to be a silent log if it is a test function...
                const meta: LegacyTransformationPluginMeta = {
                    config: invocation.globals.inputs,
                    global: {},
                    logger: logger,
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
                            fetch,
                        })
                    }
                }

                state = this.pluginState[pluginId] = {
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

            status.info('⚡️', 'Executing plugin', {
                pluginId,
                invocationId: invocation.id,
            })

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
                })
            } else {
                // Transformation style
                const transformedEvent = plugin.processEvent(event as PluginEvent, {
                    ...state.meta,
                    logger,
                })
                result.execResult = transformedEvent
            }

            addLog('debug', `Execution successful`)
            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }

            status.error('💩', 'Plugin errored', {
                error: e,
                pluginId,
                invocationId: invocation.id,
            })

            result.error = e

            addLog('error', `Plugin execution failed: ${e.message}`)
        }

        return result
    }
}
