import { Plugin, PluginEvent, PluginMeta, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { Hub, PluginConfig, PluginConfigVMInternalResponse, PluginTaskType } from '../../../types'
import { isTestEnv } from '../../../utils/env-utils'
import { stringClamp } from '../../../utils/utils'
import { ExportEventsBuffer } from './utils/export-events-buffer'

export const MAXIMUM_RETRIES = 3
const EXPORT_BUFFER_BYTES_MINIMUM = 1
const EXPORT_BUFFER_BYTES_DEFAULT = 900 * 1024 // 900 KiB
const EXPORT_BUFFER_BYTES_MAXIMUM = 100 * 1024 * 1024
const EXPORT_BUFFER_SECONDS_MINIMUM = 1
const EXPORT_BUFFER_SECONDS_MAXIMUM = 600
const EXPORT_BUFFER_SECONDS_DEFAULT = isTestEnv() ? 0 : 10

export const appRetriesCounter = new Counter({
    name: 'export_app_retries',
    help: 'Count of events retries processing onEvent apps, by team and plugin.',
    labelNames: ['team_id', 'plugin_id'],
})

type ExportEventsUpgrade = Plugin<{
    global: {
        exportEventsBuffer: ExportEventsBuffer
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

    meta.global.exportEventsToIgnore = new Set(
        meta.config.exportEventsToIgnore
            ? meta.config.exportEventsToIgnore.split(',').map((event: string) => event.trim())
            : null
    )

    meta.global.exportEventsBuffer = new ExportEventsBuffer(hub, pluginConfig, {
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
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        meta: PluginMeta<ExportEventsUpgrade>
    ) => {
        try {
            await methods.exportEvents?.(payload.batch)
            await hub.appMetrics.queueMetric({
                teamId: pluginConfig.team_id,
                pluginConfigId: pluginConfig.id,
                category: 'exportEvents',
                successes: payload.batch.length,
            })
        } catch (err) {
            // We've disabled all retries as we move exportEvents to a new system
            await hub.appMetrics.queueError(
                {
                    teamId: pluginConfig.team_id,
                    pluginConfigId: pluginConfig.id,
                    category: 'exportEvents',
                    failures: payload.batch.length,
                },
                {
                    error: err,
                    eventCount: payload.batch.length,
                }
            )
        }
    }

    tasks.job['exportEventsWithRetry'] = {
        name: 'exportEventsWithRetry',
        type: PluginTaskType.Job,
        exec: (payload) => meta.global.exportEventsWithRetry(payload as ExportEventsJobPayload, meta),
    }

    const oldOnEvent = methods.onEvent
    methods.onEvent = async (event: ProcessedPluginEvent) => {
        if (!meta.global.exportEventsToIgnore.has(event.event)) {
            await meta.global.exportEventsBuffer.add(event, JSON.stringify(event).length)
        }
        await oldOnEvent?.(event)
    }

    const oldTeardownPlugin = methods.teardownPlugin
    methods.teardownPlugin = async () => {
        await Promise.all([meta.global.exportEventsBuffer.flush(), oldTeardownPlugin?.()])
    }
}
