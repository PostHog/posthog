import Piscina from '@posthog/piscina'
import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PreIngestionEvent, Queue, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
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
        runBufferEventPipeline: (event: PreIngestionEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'runBufferEventPipeline'
            return piscina.run({ task: 'runBufferEventPipeline', args: { event } })
        },
        runAsyncHandlersEventPipeline: (event: ProcessedPluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'runAsyncHandlersEventPipeline'
            return piscina.run({ task: 'runAsyncHandlersEventPipeline', args: { event } })
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
