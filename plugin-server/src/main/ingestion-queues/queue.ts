import Piscina from '@posthog/piscina'
import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PreIngestionEvent, Queue, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { Action } from './../../types'
import { KafkaQueue } from './kafka-queue'

interface Queues {
    ingestion: Queue | null
}

export function pauseQueueIfWorkerFull(
    pause: undefined | (() => void | Promise<void>),
    server: Hub,
    piscina?: Piscina
): void {
    if (pause && (piscina?.queueSize || 0) > (server.WORKER_CONCURRENCY || 4) * (server.WORKER_CONCURRENCY || 4)) {
        void pause()
    }
}

export async function startQueues(
    server: Hub,
    piscina: Piscina,
    workerMethods: Partial<WorkerMethods> = {}
): Promise<Queues> {
    const mergedWorkerMethods = {
        onEvent: (event: ProcessedPluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'onEvent'
            return piscina.run({ task: 'onEvent', args: { event } })
        },
        onAction: (action: Action, event: ProcessedPluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'onAction'
            return piscina.run({ task: 'onAction', args: { event, action } })
        },
        onSnapshot: (event: ProcessedPluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'onSnapshot'
            return piscina.run({ task: 'onSnapshot', args: { event } })
        },
        processEvent: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'processEvent'
            return piscina.run({ task: 'processEvent', args: { event } })
        },
        ingestEvent: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'ingestEvent'
            return piscina.run({ task: 'ingestEvent', args: { event } })
        },
        ingestBufferEvent: (event: PreIngestionEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'ingestBufferEvent'
            return piscina.run({ task: 'ingestBufferEvent', args: { event } })
        },
        runEventPipeline: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'runEventPipeline'
            return piscina.run({ task: 'runEventPipeline', args: { event } })
        },
        ...workerMethods,
    }

    try {
        const queues: Queues = {
            ingestion: await startQueueKafka(server, mergedWorkerMethods),
        }
        return queues
    } catch (error) {
        status.error('💥', 'Failed to start event queue:\n', error)
        throw error
    }
}

async function startQueueKafka(server: Hub, workerMethods: WorkerMethods): Promise<Queue | null> {
    if (!server.capabilities.ingestion) {
        return null
    }

    const kafkaQueue: Queue = new KafkaQueue(server, workerMethods)
    await kafkaQueue.start()

    return kafkaQueue
}
