import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { Hub } from '../../types'
import { Response, trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { DESTINATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyPluginLogger, LegacyPluginMeta } from '../legacy-plugins/types'
import { sanitizeLogMessage } from '../services/hog-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult } from '../types'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_plugin_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

export type PluginState = {
    setupPromise: Promise<any>
    errored: boolean
    meta: LegacyPluginMeta
}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class LegacyPluginExecutorService {
    constructor(private hub: Hub) {}

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

        const pluginId = invocation.hogFunction.template_id?.startsWith('plugin-')
            ? invocation.hogFunction.template_id.replace('plugin-', '')
            : null

        const isTestFunction = invocation.hogFunction.name.includes('[CDP-TEST-HIDDEN]')

        result.logs.push({
            level: 'debug',
            timestamp: DateTime.now(),
            message: `Executing plugin ${pluginId}`,
        })
        const plugin = pluginId ? DESTINATION_PLUGINS_BY_ID[pluginId] : null

        if (!plugin || !pluginId) {
            result.error = new Error(`Plugin ${pluginId} not found`)
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} not found`,
            })
            return result
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

        let state = this.pluginState[pluginId]

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

        if (!state) {
            // TODO: Modify fetch to be a silent log if it is a test function...
            const meta: LegacyPluginMeta = {
                config: invocation.globals.inputs,
                global: {},
                fetch,
                logger: logger,
            }

            state = this.pluginState[pluginId] = {
                setupPromise: plugin.setupPlugin?.(meta) ?? Promise.resolve(),
                meta,
                errored: false,
            }
        }

        try {
            await state.setupPromise
        } catch (e) {
            state.errored = true
            result.error = e
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} setup failed: ${e.message}`,
            })
            return result
        }

        // Convert the invocation into the right interface for the plugin

        const event: ProcessedPluginEvent = {
            distinct_id: invocation.globals.event.distinct_id,
            ip: invocation.globals.event.properties.$ip,
            team_id: invocation.hogFunction.team_id,
            event: invocation.globals.event.event,
            properties: invocation.globals.event.properties,
            timestamp: invocation.globals.event.timestamp,
            $set: invocation.globals.event.properties.$set,
            $set_once: invocation.globals.event.properties.$set_once,
            uuid: invocation.globals.event.uuid,
            person: invocation.globals.person
                ? {
                      uuid: invocation.globals.person.id,
                      team_id: invocation.hogFunction.team_id,
                      properties: invocation.globals.person.properties,
                      created_at: '', // NOTE: We don't have this anymore - see if any plugin uses it...
                  }
                : undefined,
        }

        const start = performance.now()

        try {
            status.info('⚡️', 'Executing plugin', {
                pluginId,
                invocationId: invocation.id,
            })

            await plugin.onEvent?.(event, {
                ...state.meta,
                // NOTE: We override logger and fetch here so we can track the calls
                logger,
                fetch,
            })
            result.logs.push({
                level: 'debug',
                timestamp: DateTime.now(),
                message: `Execution successful`,
            })
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
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin errored: ${e.message}`,
            })
        } finally {
            pluginExecutionDuration.observe(performance.now() - start)
        }

        return result
    }
}
