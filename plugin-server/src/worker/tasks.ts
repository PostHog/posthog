import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Action, EnqueuedPluginJob, Hub, PluginTaskType, Team } from '../types'
import { loadSchedule } from './plugins/loadSchedule'
import { runOnEvent, runPluginTask, runProcessEvent } from './plugins/run'
import { setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'

type TaskRunner = (hub: Hub, args: any) => Promise<any> | any

export const workerTasks: Record<string, TaskRunner> = {
    runOnEvent: async (hub: Hub, event: ProcessedPluginEvent) => {
        return await runOnEvent(hub, event)
    },
    runProcessEvent: async (hub: Hub, event: PluginEvent) => {
        return await runProcessEvent(hub, event)
    },
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
        await setupPlugins(hub)
    },
    reloadSchedule: async (hub) => {
        await loadSchedule(hub)
    },
    reloadAllActions: async (hub) => {
        return await hub.actionManager.reloadAllActions()
    },
    reloadAction: async (hub, args: { teamId: Team['id']; actionId: Action['id'] }) => {
        return await hub.actionManager.reloadAction(args.teamId, args.actionId)
    },
    dropAction: (hub, args: { teamId: Team['id']; actionId: Action['id'] }) => {
        return hub.actionManager.dropAction(args.teamId, args.actionId)
    },
    teardownPlugins: async (hub) => {
        await teardownPlugins(hub)
    },
    flushKafkaMessages: async (hub) => {
        await hub.kafkaProducer.flush()
    },
    resetAvailableFeaturesCache: (hub, args: { organization_id: string }) => {
        hub.organizationManager.resetAvailableFeatureCache(args.organization_id)
    },
    // Exported only for tests
    _testsRunProcessEvent: async (hub, args: { event: PluginEvent }) => {
        return runProcessEvent(hub, args.event)
    },
}
