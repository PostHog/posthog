import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, WorkerMethods } from '../../../types'
import { status } from '../../../utils/status'
import { sanitizeEvent } from '../../../utils/utils'
import { KafkaQueue } from '../kafka-queue'
import { eachBatch } from './each-batch'
export interface KafkaEvent {
    uuid: string
    distinct_id: string
    ip: string | null
    site_url: string
    team_id: number
    now: string
    sent_at?: string
    offset?: number
    event: string
    properties?: string
    timestamp?: string
    $set?: string
    $set_once?: string

    // KLUDGE: We need to make sure the plugin server can still process events in the old format during the transition period
    // `data` is deprecated and we should remove it in the future
    data: string
}

export async function eachMessageIngestion(message: KafkaMessage, queue: KafkaQueue): Promise<void> {
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString()) as KafkaEvent
    const event: PluginEvent = sanitizeEvent({
        ...rawEvent,
        properties: JSON.parse(rawEvent.properties || '{}'),
        $set: JSON.parse(rawEvent.$set || '{}'),
        $set_once: JSON.parse(rawEvent.$set_once || '{}'),
        site_url: rawEvent.site_url || '',
        ip: rawEvent.ip || null,
        ...JSON.parse(dataStr || '{}'),
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
