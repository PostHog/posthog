import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Action, Alert, EnqueuedJob, Hub, PluginTaskType, PreIngestionEvent, Team } from '../types'
import { runEventPipeline } from './ingestion/event-pipeline'
import { ingestBufferEvent, ingestEvent } from './ingestion/ingest-event'
import { runHandleAlert, runOnAction, runOnEvent, runOnSnapshot, runPluginTask, runProcessEvent } from './plugins/run'
import { loadSchedule, setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'

type TaskRunner = (hub: Hub, args: any) => Promise<any> | any

export const workerTasks: Record<string, TaskRunner> = {
    onEvent: (hub, args: { event: ProcessedPluginEvent }) => {
        return runOnEvent(hub, args.event)
    },
    onAction: (hub, args: { event: ProcessedPluginEvent; action: Action }) => {
        return runOnAction(hub, args.action, args.event)
    },
    onSnapshot: (hub, args: { event: ProcessedPluginEvent }) => {
        return runOnSnapshot(hub, args.event)
    },
    processEvent: (hub, args: { event: PluginEvent }) => {
        return runProcessEvent(hub, args.event)
    },
    handleAlert: async (hub, args: { alert: Alert }) => {
        return runHandleAlert(hub, args.alert)
    },
    runJob: (hub, { job }: { job: EnqueuedJob }) => {
        return runPluginTask(hub, job.type, PluginTaskType.Job, job.pluginConfigId, job.payload)
    },
    runEveryMinute: (hub, args: { pluginConfigId: number }) => {
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
    runEventPipeline: async (hub, args: { event: PluginEvent }) => {
        return await runEventPipeline(hub, args.event)
    },
    ingestEvent: async (hub, args: { event: PluginEvent }) => {
        return await ingestEvent(hub, args.event)
    },
    ingestBufferEvent: async (hub, args: { event: PreIngestionEvent }) => {
        return await ingestBufferEvent(hub, args.event)
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
        await hub.kafkaProducer?.flush()
    },
    enqueueJob: async (hub, { job }: { job: EnqueuedJob }) => {
        await hub.jobQueueManager.enqueue(job)
    },
}
