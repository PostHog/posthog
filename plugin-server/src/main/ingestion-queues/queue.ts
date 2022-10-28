import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PostIngestionEvent, WorkerMethods } from '../../types'
import { convertToProcessedPluginEvent } from '../../utils/event'
import { status } from '../../utils/status'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { KafkaQueue } from './kafka-queue'

interface Queues {
    ingestion: KafkaQueue | null
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
        runAsyncHandlersEventPipeline: async (event: PostIngestionEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'runAsyncHandlersEventPipeline'
            const runner = new EventPipelineRunner(server, piscina, convertToProcessedPluginEvent(event))
            await runner.runAsyncHandlersEventPipeline(event)
        },
        runEventPipeline: async (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'runEventPipeline'
            const runner = new EventPipelineRunner(server, piscina, event)
            await runner.runEventPipeline(event)
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

async function startQueueKafka(server: Hub, workerMethods: WorkerMethods): Promise<KafkaQueue | null> {
    if (!server.capabilities.ingestion && !server.capabilities.processAsyncHandlers) {
        return null
    }

    const kafkaQueue = new KafkaQueue(server, workerMethods)
    await kafkaQueue.start()

    return kafkaQueue
}
