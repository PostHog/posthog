import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, WorkerMethods } from '../../../types'
import { status } from '../../../utils/status'
import { sanitizeEvent } from '../../../utils/utils'
import { KafkaQueue } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageIngestion(message: KafkaMessage, queue: KafkaQueue): Promise<void> {
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
    const event: PluginEvent = sanitizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    await ingestEvent(queue.pluginsServer, queue.workerMethods, event)
}

export async function eachBatchIngestion(payload: EachBatchPayload, queue: KafkaQueue): Promise<void> {
    await eachBatch(payload, queue, eachMessageIngestion, 'ingestion')
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
