import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { convertToIngestionEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { silentFailuresAsyncHandlers } from '../../../worker/ingestion/event-pipeline/runner'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

// TODO: remove once we've migrated
export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: KafkaJSIngestionConsumer): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await Promise.all([
        runInstrumentedFunction({
            event: event,
            func: () => queue.workerMethods.runAppsOnEventPipeline(event),
            statsKey: `kafka_queue.process_async_handlers_on_event`,
            timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
            teamId: event.teamId,
        }),
        runInstrumentedFunction({
            event: event,
            func: () => runWebhooks(queue.pluginsServer, event),
            statsKey: `kafka_queue.process_async_handlers_webhooks`,
            timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
            teamId: event.teamId,
        }),
    ])
}

// TODO: remove once we've migrated
export async function eachBatchAsyncHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageAsyncHandlers, groupIntoBatches, 'async_handlers')
}

export async function eachMessageAppsOnEventHandlers(
    message: KafkaMessage,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        event: event,
        func: () => queue.workerMethods.runAppsOnEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        teamId: event.teamId,
    })
}

export async function eachMessageWebhooksHandlers(
    message: KafkaMessage,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        event: event,
        func: () => runWebhooks(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_webhooks`,
        timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
        teamId: event.teamId,
    })
}

export async function eachBatchAppsOnEventHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageAppsOnEventHandlers, groupIntoBatches, 'async_handlers_on_event')
}

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageWebhooksHandlers, groupIntoBatches, 'async_handlers_webhooks')
}

async function runWebhooks(hub: Hub, event: PostIngestionEvent) {
    const timer = new Date()

    try {
        hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'webhooks' })
        await processWebhooksStep(hub, event)
        hub.statsd?.increment('kafka_queue.webhooks.processed')
        hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: processWebhooksStep.name })
        hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: processWebhooksStep.name })
    } catch (error) {
        hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: processWebhooksStep.name })

        if (error instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            status.error('Error processing webhooks', {
                stack: error.stack,
                eventUuid: event.eventUuid,
                teamId: event.teamId,
                error: error,
            })
            throw error
        }

        status.warn(`⚠️`, 'Error processing webhooks, silently moving on', {
            stack: error.stack,
            eventUuid: event.eventUuid,
            teamId: event.teamId,
            error: error,
        })
        silentFailuresAsyncHandlers.inc()
    }
}
