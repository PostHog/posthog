import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { EnqueuedPluginJob, Hub, PluginTaskType } from '../types'
import { retryIfRetriable } from '../utils/retries'
import { status } from '../utils/status'
import { sleep } from '../utils/utils'
import { loadSchedule } from './plugins/loadSchedule'
import { runPluginTask, runProcessEvent } from './plugins/run'
import { setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'
import { populatePluginCapabilities } from './vm/lazy'

type TaskRunner = (hub: Hub, args: any) => Promise<any> | any

// If a reload is already scheduled, this will be a promise that resolves when the reload is done.
let RELOAD_PLUGINS_PROMISE: Promise<void> | undefined

// Whether the actual reload work has started. If `RELOAD_PLUGINS_PROMISE` is defined and this is
// `false` it means the promise is still sleeping for jitter, and so concurrent requests can know
// that a reload will start in the future.
let RELOAD_PLUGINS_PROMISE_STARTED = false

export const workerTasks: Record<string, TaskRunner> = {
    runPluginJob: (hub, { job }: { job: EnqueuedPluginJob }) => {
        return runPluginTask(hub, job.type, PluginTaskType.Job, job.pluginConfigId, job.payload)
    },
    runEveryMinute: async (hub, args: { pluginConfigId: number }) => {
        return runPluginTask(hub, 'runEveryMinute', PluginTaskType.Schedule, args.pluginConfigId)
    },
    runEveryHour: (hub, args: { pluginConfigId: number }) => {
        return runPluginTask(hub, 'runEveryHour', PluginTaskType.Schedule, args.pluginConfigId)
    },
    runEveryDay: (hub, args: { pluginConfigId: number }) => {
        return runPluginTask(hub, 'runEveryDay', PluginTaskType.Schedule, args.pluginConfigId)
    },
    getPluginSchedule: (hub) => {
        return hub.pluginSchedule
    },
    pluginScheduleReady: (hub) => {
        return hub.pluginSchedule !== null
    },
    reloadPlugins: async (hub) => {
        if (RELOAD_PLUGINS_PROMISE && !RELOAD_PLUGINS_PROMISE_STARTED) {
            // A reload is already scheduled and hasn't started yet. When it starts it will load the
            // state of plugins after this reload request was issued, so we're done here.
            return
        }

        if (RELOAD_PLUGINS_PROMISE && RELOAD_PLUGINS_PROMISE_STARTED) {
            // A reload was in progress, we need to wait for it to finish and then we can schedule a
            // new one (or a concurrent request will beat us to it after also waiting here, which is
            // fine!).
            await RELOAD_PLUGINS_PROMISE
        }

        if (!RELOAD_PLUGINS_PROMISE) {
            // No reload is in progress, schedule one. If multiple concurrent requests got in line
            // above, we only need one to schedule the reload here.

            RELOAD_PLUGINS_PROMISE = (async () => {
                // Jitter the reload time to avoid all workers reloading at the same time.
                const jitterMs = Math.random() * hub.RELOAD_PLUGIN_JITTER_MAX_MS
                status.info('💤', `Sleeping for ${jitterMs}ms to jitter reloadPlugins`)
                await sleep(jitterMs)

                RELOAD_PLUGINS_PROMISE_STARTED = true
                try {
                    const tries = 3
                    const retrySleepMs = 5000
                    await retryIfRetriable(async () => await setupPlugins(hub), tries, retrySleepMs)
                } finally {
                    RELOAD_PLUGINS_PROMISE = undefined
                    RELOAD_PLUGINS_PROMISE_STARTED = false
                }
            })()

            await RELOAD_PLUGINS_PROMISE
        }
    },
    reloadSchedule: async (hub) => {
        await loadSchedule(hub)
    },
    teardownPlugins: async (hub) => {
        await teardownPlugins(hub)
    },
    flushKafkaMessages: async (hub) => {
        await hub.kafkaProducer.flush()
    },
    resetAvailableProductFeaturesCache: (hub, args: { organization_id: string }) => {
        hub.organizationManager.resetAvailableProductFeaturesCache(args.organization_id)
    },
    populatePluginCapabilities: async (hub, args: { plugin_id: string }) => {
        await populatePluginCapabilities(hub, Number(args.plugin_id))
    },
    // Exported only for tests
    _testsRunProcessEvent: async (hub, args: { event: PluginEvent }) => {
        return runProcessEvent(hub, args.event)
    },
}
