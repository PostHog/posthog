import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageIngestion(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    await ingestEvent(queue.pluginsServer, queue.workerMethods, formPipelineEvent(message))
}

export async function eachBatchIngestion(payload: EachBatchPayload, queue: IngestionConsumer): Promise<void> {
    await eachBatch(payload, queue, eachMessageIngestion, groupIntoBatches, 'ingestion')
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
