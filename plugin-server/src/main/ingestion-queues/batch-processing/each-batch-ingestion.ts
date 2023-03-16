import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KAFKA_SESSION_RECORDING_EVENTS } from '../../../config/kafka-topics'
import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageIngestion(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    const event = formPipelineEvent(message)

    if (['$snapshot', '$performance_event'].includes(event.event)) {
        // We have switched to using a separate topic for session recording
        // related events. On upgrading PostHog there may be some session
        // recording events still in the main ingestion topic.
        await queue.pluginsServer.kafkaProducer.queueMessage({
            topic: KAFKA_SESSION_RECORDING_EVENTS,
            messages: [message],
        })
        return
    }

    await ingestEvent(queue.pluginsServer, queue.workerMethods, event)
}

export async function eachBatchIngestion(payload: EachBatchPayload, queue: IngestionConsumer): Promise<void> {
    function groupIntoBatchesIngestion(kafkaMessages: KafkaMessage[], batchSize: number): KafkaMessage[][] {
        // Once we see a distinct ID we've already seen break up the batch
        const batches = []
        const seenIds: Set<string> = new Set()
        let currentBatch: KafkaMessage[] = []
        for (const message of kafkaMessages) {
            const pluginEvent = formPipelineEvent(message)
            const seenKey = `${pluginEvent.team_id}:${pluginEvent.distinct_id}`
            if (currentBatch.length === batchSize || seenIds.has(seenKey)) {
                seenIds.clear()
                batches.push(currentBatch)
                currentBatch = []
            }
            seenIds.add(seenKey)
            currentBatch.push(message)
        }
        if (currentBatch) {
            batches.push(currentBatch)
        }
        return batches
    }

    await eachBatch(payload, queue, eachMessageIngestion, groupIntoBatchesIngestion, 'ingestion')
}

export async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PipelineEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<void> {
    const eachEventStartTimer = new Date()

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit', {
        pipeline: 'runEventPipeline',
    })
    await workerMethods.runEventPipeline(event)

    server.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)

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
