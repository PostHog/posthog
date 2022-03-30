import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { PluginServerMode } from '../../types'
import { CeleryTriggeredJobOperation, Hub, PluginConfig, Queue, Team, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { Action } from './../../types'
import { CeleryQueue } from './celery-queue'
import { KafkaQueue } from './kafka-queue'

interface Queues {
    ingestion: Queue
    auxiliary: Queue
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
    workerMethods: Partial<WorkerMethods> = {},
    pluginServerMode: PluginServerMode = PluginServerMode.Ingestion
): Promise<Queues> {
    const workerMethodsForMode =
        pluginServerMode === PluginServerMode.Ingestion
            ? {
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
                  onAction: (action: Action, event: PluginEvent) => {
                      server.lastActivity = new Date().valueOf()
                      server.lastActivityType = 'onAction'
                      return piscina.run({ task: 'onAction', args: { event, action } })
                  },
              }
            : {
                  onEvent: (event: PluginEvent) => {
                      server.lastActivity = new Date().valueOf()
                      server.lastActivityType = 'onEvent'
                      return piscina.run({ task: 'onEvent', args: { event } })
                  },
                  onSnapshot: (event: PluginEvent) => {
                      server.lastActivity = new Date().valueOf()
                      server.lastActivityType = 'onSnapshot'
                      return piscina.run({ task: 'onSnapshot', args: { event } })
                  },
              }
    const mergedWorkerMethods = {
        ...workerMethodsForMode,
        ...workerMethods,
    }

    try {
        const redisQueue = startQueueRedis(server, piscina, mergedWorkerMethods)
        const queues = {
            ingestion: redisQueue,
            auxiliary: redisQueue,
        }
        console.log('about to startQueueKafka 1', pluginServerMode, server.KAFKA_ENABLED)
        if (server.KAFKA_ENABLED) {
            console.log('about to startQueueKafka 2', pluginServerMode)
            queues.ingestion = await startQueueKafka(server, mergedWorkerMethods, pluginServerMode)
        }
        return queues
    } catch (error) {
        status.error('💥', 'Failed to start event queue:\n', error)
        throw error
    }
}

function startQueueRedis(server: Hub, piscina: Piscina, workerMethods: WorkerMethods): Queue {
    const celeryQueue = new CeleryQueue(server.db, server.PLUGINS_CELERY_QUEUE)

    // this queue is for triggering plugin jobs from the PostHog UI
    celeryQueue.register(
        'posthog.tasks.plugins.plugin_job',
        async (
            pluginConfigTeam: Team['id'],
            pluginConfigId: PluginConfig['id'],
            type: string,
            jobOp: CeleryTriggeredJobOperation,
            payload: Record<string, any>
        ) => {
            try {
                payload['$operation'] = jobOp
                const job = {
                    type,
                    payload,
                    pluginConfigId,
                    pluginConfigTeam,
                    timestamp: Date.now(),
                }
                pauseQueueIfWorkerFull(() => celeryQueue.pause(), server, piscina)
                await piscina?.run({ task: 'enqueueJob', args: { job } })
            } catch (e) {
                Sentry.captureException(e)
            }
        }
    )

    // run in the background
    void celeryQueue.start()

    return celeryQueue
}

async function startQueueKafka(
    server: Hub,
    workerMethods: WorkerMethods,
    pluginServerMode: PluginServerMode
): Promise<Queue> {
    console.log('about to new KafkaQueue', pluginServerMode)
    const kafkaQueue: Queue = new KafkaQueue(server, workerMethods, pluginServerMode)
    await kafkaQueue.start()

    return kafkaQueue
}
