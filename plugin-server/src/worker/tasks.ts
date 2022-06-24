import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Action, EnqueuedJob, Hub, IngestionEvent, PluginTaskType, Team } from '../types'
import { convertToProcessedPluginEvent } from '../utils/event'
import { EventPipelineRunner } from './ingestion/event-pipeline/runner'
import { runPluginTask, runProcessEvent } from './plugins/run'
import { loadSchedule, setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'

type TaskRunner = (hub: Hub, args: any) => Promise<any> | any

export const workerTasks: Record<string, TaskRunner> = {
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
    pluginScheduleReady: (hub) => {
        return hub.pluginSchedule !== null
    },
    runEventPipeline: async (hub, args: { event: PluginEvent }) => {
        const runner = new EventPipelineRunner(hub, args.event)
        return await runner.runEventPipeline(args.event)
    },
    runBufferEventPipeline: async (hub, args: { event: PluginEvent }) => {
        const runner = new EventPipelineRunner(hub, args.event)
        return await runner.runBufferEventPipeline(args.event)
    },
    runAsyncHandlersEventPipeline: async (hub, args: { event: IngestionEvent }) => {
        const runner = new EventPipelineRunner(hub, convertToProcessedPluginEvent(args.event))
        return await runner.runAsyncHandlersEventPipeline(args.event)
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
    enqueueJob: async (hub, { job }: { job: EnqueuedJob }) => {
        await hub.jobQueueManager.enqueue(job)
    },
    // Exported only for tests
    _testsRunProcessEvent: async (hub, args: { event: PluginEvent }) => {
        return runProcessEvent(hub, args.event)
    },
}
