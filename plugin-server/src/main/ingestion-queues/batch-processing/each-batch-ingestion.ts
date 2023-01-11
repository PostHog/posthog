import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageIngestion(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    await ingestEvent(queue.pluginsServer, queue.workerMethods, formPipelineEvent(message))
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

            // If if is a `$snapshot` event or `$performance_event`, i.e. the
            // ones related to session recordings, we do not need to ensure that
            // we process the events in order. This is because we do not do any
            // person detail updates based on these events, and we do not need
            // to ensure that we process them in order to get the correct
            // session recording as ClickHouse will handle ordering at realtime.
            //
            // By not ordering these, we can avoid the case that we are creating
            // small batches if there is a badly behaved client sending lots of
            // session recording dom mutations.
            if (!['$snapshot', '$performance_event'].includes(pluginEvent.event)) {
                seenIds.add(seenKey)
            }

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

    // Eventually no events will have a team_id as that will be determined and
    // populated in the plugin server rather than the capture endpoint. However,
    // we support both paths during the transitional period.
    if (event.team_id) {
        server.statsd?.increment('kafka_queue_ingest_event_hit', { pipeline: 'runEventPipeline' })
        // we've confirmed team_id exists so can assert event as PluginEvent
        await workerMethods.runEventPipeline(event as PluginEvent)
    } else {
        server.statsd?.increment('kafka_queue_ingest_event_hit', {
            pipeline: 'runLightweightCaptureEndpointEventPipeline',
        })
        await workerMethods.runLightweightCaptureEndpointEventPipeline(event)
    }

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
