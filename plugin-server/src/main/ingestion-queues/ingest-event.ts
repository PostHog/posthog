import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { groupIntoBatches, sanitizeEvent } from '../../utils/utils'
import { IngestionQueue } from './ingestion-queue'

export async function eachMessageIngestion(message: KafkaMessage, ingestionQueue: IngestionQueue): Promise<void> {
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
    const event: PluginEvent = sanitizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    await ingestEvent(ingestionQueue.pluginsServer, ingestionQueue.workerMethods, event)
}

export async function eachBatchIngestion(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    ingestionQueue: IngestionQueue
): Promise<void> {
    const batchStartTimer = new Date()

    try {
        const messageBatches = groupIntoBatches(
            batch.messages,
            ingestionQueue.pluginsServer.WORKER_CONCURRENCY * ingestionQueue.pluginsServer.TASKS_PER_WORKER
        )

        for (const messageBatch of messageBatches) {
            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                return
            }

            await Promise.all(messageBatch.map((message) => eachMessageIngestion(message, ingestionQueue)))

            // this if should never be false, but who can trust computers these days
            if (messageBatch.length > 0) {
                resolveOffset(messageBatch[messageBatch.length - 1].offset)
            }
            await commitOffsetsIfNecessary()
            await heartbeat()
        }

        status.info(
            '🧩',
            `Kafka batch of ${batch.messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms`
        )
    } finally {
        ingestionQueue.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchStartTimer)
    }
}

export async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<void> {
    const eachEventStartTimer = new Date()

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit')

    await workerMethods.runEventPipeline(event)

    server.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)
    server.internalMetrics?.incr('$$plugin_server_events_processed')

    countAndLogEvents()
}

let messageCounter = 0
let messageLogDate = 0

function countAndLogEvents(): void {
    const now = new Date().valueOf()
    messageCounter++
    if (now - messageLogDate > 10000) {
        status.info(
            '🕒',
            `Processed ${messageCounter} events${
                messageLogDate === 0 ? '' : ` in ${Math.round((now - messageLogDate) / 10) / 100}s`
            }`
        )
        messageCounter = 0
        messageLogDate = now
    }
}
