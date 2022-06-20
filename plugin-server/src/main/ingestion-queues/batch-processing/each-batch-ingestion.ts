import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, WorkerMethods } from '../../../types'
import { normalizeEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { KafkaQueue } from '../kafka-queue'
import { eachBatch } from './each-batch'

export function formPluginEvent(message: KafkaMessage): PluginEvent {
    // TODO: inefficient to do this twice?
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
    const event: PluginEvent = normalizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    return event
}

export async function eachMessageIngestion(message: KafkaMessage, queue: KafkaQueue): Promise<void> {
    await ingestEvent(queue.pluginsServer, queue.workerMethods, formPluginEvent(message))
}

export async function eachBatchIngestion(payload: EachBatchPayload, queue: KafkaQueue): Promise<void> {
    const enabledTeams = queue.pluginsServer.ingestionBatchBreakupByDistinctIdTeams
    const countingMode = enabledTeams.size === 0

    function groupIntoBatchesIngestion(kafkaMessages: KafkaMessage[], batchSize: number): KafkaMessage[][] {
        // Once we see a distinct ID we've already seen break up the batch
        const batches = []
        const seenIds: Set<string> = new Set()
        let currentBatch: KafkaMessage[] = []
        for (const message of kafkaMessages) {
            const pluginEvent = formPluginEvent(message)
            const enabledBreakupById = countingMode || enabledTeams.has(pluginEvent.team_id)
            const seenKey = `${pluginEvent.team_id}:${pluginEvent.distinct_id}`
            if (currentBatch.length === batchSize || (enabledBreakupById && seenIds.has(seenKey))) {
                seenIds.clear()
                batches.push(currentBatch)
                currentBatch = []
            }
            if (enabledBreakupById) {
                seenIds.add(seenKey)
            }
            currentBatch.push(message)
        }
        if (currentBatch) {
            batches.push(currentBatch)
        }
        if (countingMode) {
            queue.pluginsServer.statsd?.histogram(
                'ingest_event_batching.batch_count_if_enabled_for_all',
                batches.length
            )
            return groupIntoBatches(kafkaMessages, batchSize)
        }
        return batches
    }

    await eachBatch(payload, queue, eachMessageIngestion, groupIntoBatchesIngestion, 'ingestion')
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
