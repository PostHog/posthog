import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { Response, trackedFetch } from '../../utils/fetch'
import { logger } from '../../utils/logger'
import { DESTINATION_PLUGINS_BY_ID, TRANSFORMATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyPluginLogger, LegacyTransformationPlugin } from '../legacy-plugins/types'
import { sanitizeLogMessage } from '../services/hog-executor.service'
import { HogFunctionTemplate } from '../templates/types'
import { HogFunctionInvocation, HogFunctionInvocationResult } from '../types'
import { CDP_TEST_ID, isSegmentPluginHogFunction } from '../utils'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_segment_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

export type SegmentPluginMeta = {
    config: Record<string, any>
    global: Record<string, any>
    logger: LegacyPluginLogger
}

export type SegmentDestinationPluginMeta = SegmentPluginMeta & {
    fetch: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export type SegmentDestinationPlugin = {
    template: HogFunctionTemplate
    onEvent(event: ProcessedPluginEvent, meta: SegmentDestinationPluginMeta): Promise<void>
}

export type PluginState = {
    setupPromise: Promise<any>
    errored: boolean
    meta: SegmentDestinationPluginMeta
}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */

export type SegmentPluginExecutorOptions = {
    fetch?: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export class SegmentPluginExecutorService {
    private pluginState: Record<string, PluginState> = {}

    public async fetch(...args: Parameters<typeof trackedFetch>): Promise<Response> {
        return trackedFetch(...args)
    }

    public async execute(
        invocation: HogFunctionInvocation,
        options?: SegmentPluginExecutorOptions
    ): Promise<HogFunctionInvocationResult> {
        const result: HogFunctionInvocationResult = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
            metrics: [],
        }

        const addLog = (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
            result.logs.push({
                level,
                timestamp: DateTime.now(),
                message: sanitizeLogMessage(args),
            })
        }

        const pluginLogger: LegacyPluginLogger = {
            debug: (...args: any[]) => addLog('debug', ...args),
            warn: (...args: any[]) => addLog('warn', ...args),
            log: (...args: any[]) => addLog('info', ...args),
            error: (...args: any[]) => addLog('error', ...args),
        }

        const pluginId = isSegmentPluginHogFunction(invocation.hogFunction) ? invocation.hogFunction.template_id : null

        try {
            const plugin = pluginId
                ? ((DESTINATION_PLUGINS_BY_ID[pluginId] || TRANSFORMATION_PLUGINS_BY_ID[pluginId]) as
                      | LegacyTransformationPlugin
                      | SegmentDestinationPlugin)
                : null

            if (!pluginId || !plugin) {
                throw new Error(`Plugin ${pluginId} not found`)
            }

            if (invocation.hogFunction.type === 'destination' && 'processEvent' in plugin) {
                throw new Error(`Plugin ${pluginId} is not a destination`)
            }

            const isTestFunction = invocation.hogFunction.name.includes(CDP_TEST_ID)

            const fetch = async (...args: Parameters<typeof trackedFetch>) => {
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
                        json: () =>
                            Promise.resolve({
                                status: 'OK',
                                message: 'Test function',
                            }),
                    } as Response
                }

                return (options?.fetch || this.fetch)(...args)
            }

            const start = performance.now()

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
                    ip: null, // convertToOnEventPayload removes this so we should too
                    // NOTE: We want to improve validation of these properties but for now for legacy plugins we just cast
                    properties: event.properties as ProcessedPluginEvent['properties'],
                    $set: event.$set as ProcessedPluginEvent['$set'],
                    $set_once: event.$set_once as ProcessedPluginEvent['$set_once'],
                }

                const start = performance.now()

                await plugin.onEvent?.(processedEvent, {
                    config: invocation.globals.inputs,
                    global: {},
                    // NOTE: We override logger and fetch here so we can track the calls
                    logger: pluginLogger,
                    fetch,
                })

                addLog('info', `Function completed in ${performance.now() - start}ms.`)
            }

            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }

            logger.error('💩', 'Plugin errored', {
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
