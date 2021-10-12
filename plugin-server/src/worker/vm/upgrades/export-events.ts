import { createBuffer } from '@posthog/plugin-contrib'
import { Plugin, PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'

import { Hub, MetricMathOperations, PluginConfig, PluginConfigVMInternalResponse, PluginTaskType } from '../../../types'
import { status } from '../../../utils/status'
import { determineNodeEnv, stringClamp } from '../../../utils/utils'
import { NodeEnv } from './../../../utils/utils'

const MAXIMUM_RETRIES = 15
const EXPORT_BUFFER_BYTES_MINIMUM = 1
const EXPORT_BUFFER_BYTES_DEFAULT = 1024 * 1024
const EXPORT_BUFFER_BYTES_MAXIMUM = 100 * 1024 * 1024
const EXPORT_BUFFER_SECONDS_MINIMUM = 1
const EXPORT_BUFFER_SECONDS_MAXIMUM = 600
const EXPORT_BUFFER_SECONDS_DEFAULT = determineNodeEnv() === NodeEnv.Test ? EXPORT_BUFFER_SECONDS_MAXIMUM : 10

type ExportEventsUpgrade = Plugin<{
    global: {
        exportEventsBuffer: ReturnType<typeof createBuffer>
        exportEventsToIgnore: Set<string>
        exportEventsWithRetry: (payload: ExportEventsJobPayload, meta: PluginMeta<ExportEventsUpgrade>) => Promise<void>
    }
    config: {
        exportEventsBufferBytes: string
        exportEventsBufferSeconds: string
        exportEventsToIgnore: string
    }
    jobs: {
        exportEventsWithRetry: ExportEventsJobPayload
    }
}>

interface ExportEventsJobPayload extends Record<string, any> {
    batch: PluginEvent[]
    batchId: number
    retriesPerformedSoFar: number
}

/**
 * Inject export abstraction code into plugin VM if it has method `exportEvents`:
 * - add `global`/`config`/`jobs` stuff specified in the `ExportEventsUpgrade` type above,
 * - patch `onEvent` with code to add the event to a buffer.
 */
export function upgradeExportEvents(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportEventsUpgrade>>
): void {
    const { methods, tasks, meta } = response

    const uploadBytes = stringClamp(
        meta.config.exportEventsBufferBytes,
        EXPORT_BUFFER_BYTES_DEFAULT,
        EXPORT_BUFFER_BYTES_MINIMUM,
        EXPORT_BUFFER_BYTES_MAXIMUM
    )
    const uploadSeconds = stringClamp(
        meta.config.exportEventsBufferSeconds,
        EXPORT_BUFFER_SECONDS_DEFAULT,
        EXPORT_BUFFER_SECONDS_MINIMUM,
        EXPORT_BUFFER_SECONDS_MAXIMUM
    )

    function incrementMetric(metricName: string, value: number) {
        hub.pluginMetricsManager.updateMetric({
            metricName,
            value,
            pluginConfig,
            metricOperation: MetricMathOperations.Increment,
        })
    }

    meta.global.exportEventsToIgnore = new Set(
        meta.config.exportEventsToIgnore
            ? meta.config.exportEventsToIgnore.split(',').map((event: string) => event.trim())
            : null
    )

    meta.global.exportEventsBuffer = createBuffer({
        limit: uploadBytes,
        timeoutSeconds: uploadSeconds,
        onFlush: async (batch) => {
            const jobPayload = {
                batch,
                batchId: Math.floor(Math.random() * 1000000),
                retriesPerformedSoFar: 0,
            }
            // Running the first export code directly, without a job in between
            await meta.global.exportEventsWithRetry(jobPayload, meta)
        },
    })

    meta.global.exportEventsWithRetry = async (
        payload: ExportEventsJobPayload,
        meta: PluginMeta<ExportEventsUpgrade>
    ) => {
        const start = new Date()
        try {
            if (!payload.retriesPerformedSoFar) {
                incrementMetric('events_seen', payload.batch.length)
            }
            await methods.exportEvents?.(payload.batch)
            hub.statsd?.timing('plugin.export_events.success', start, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: pluginConfig.team_id.toString(),
            })
            incrementMetric('events_delivered_successfully', payload.batch.length)
        } catch (err) {
            if (err instanceof RetryError) {
                incrementMetric('retry_errors', payload.batch.length)
                if (payload.retriesPerformedSoFar < MAXIMUM_RETRIES) {
                    const nextRetrySeconds = 2 ** (payload.retriesPerformedSoFar + 1) * 3
                    await meta.jobs
                        .exportEventsWithRetry({ ...payload, retriesPerformedSoFar: payload.retriesPerformedSoFar + 1 })
                        .runIn(nextRetrySeconds, 'seconds')

                    status.info(
                        '🚃',
                        `Enqueued PluginConfig ${pluginConfig.id} batch ${payload.batchId} for retry #${
                            payload.retriesPerformedSoFar + 1
                        } in ${Math.round(nextRetrySeconds)}s`
                    )
                    hub.statsd?.increment('plugin.export_events.retry_enqueued', {
                        retry: `${payload.retriesPerformedSoFar + 1}`,
                        plugin: pluginConfig.plugin?.name ?? '?',
                        teamId: pluginConfig.team_id.toString(),
                    })
                } else {
                    incrementMetric('undelivered_events', payload.batch.length)
                    status.info(
                        '☠️',
                        `Dropped PluginConfig ${pluginConfig.id} batch ${payload.batchId} after retrying ${payload.retriesPerformedSoFar} times`
                    )
                    hub.statsd?.increment('plugin.export_events.retry_dropped', {
                        retry: `${payload.retriesPerformedSoFar}`,
                        plugin: pluginConfig.plugin?.name ?? '?',
                        teamId: pluginConfig.team_id.toString(),
                    })
                }
            } else {
                incrementMetric('other_errors', payload.batch.length)
                incrementMetric('undelivered_events', payload.batch.length)
                throw err
            }
        }
    }

    tasks.job['exportEventsWithRetry'] = {
        name: 'exportEventsWithRetry',
        type: PluginTaskType.Job,
        exec: (payload) => meta.global.exportEventsWithRetry(payload as ExportEventsJobPayload, meta),
    }

    const oldOnEvent = methods.onEvent
    methods.onEvent = async (event: PluginEvent) => {
        if (!meta.global.exportEventsToIgnore.has(event.event)) {
            meta.global.exportEventsBuffer.add(event, JSON.stringify(event).length)
        }
        await oldOnEvent?.(event)
    }

    const oldTeardownPlugin = methods.teardownPlugin
    methods.teardownPlugin = async () => {
        await Promise.all([meta.global.exportEventsBuffer.flush(), oldTeardownPlugin?.()])
    }
}
