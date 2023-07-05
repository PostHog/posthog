import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KAFKA_ON_EVENT_RETRIES_1, KAFKA_ON_EVENT_RETRIES_2 } from '../../../config/kafka-topics'
import { RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

// TODO: remove once we've migrated
export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: KafkaJSIngestionConsumer): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await Promise.all([
        runInstrumentedFunction({
            server: queue.pluginsServer,
            event: event,
            func: () => queue.workerMethods.runAppsOnEventPipeline(event),
            statsKey: `kafka_queue.process_async_handlers_on_event`,
            timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
            teamId: event.teamId,
        }),
        runInstrumentedFunction({
            server: queue.pluginsServer,
            event: event,
            func: () => queue.workerMethods.runWebhooksHandlersEventPipeline(event),
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
        server: queue.pluginsServer,
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
        server: queue.pluginsServer,
        event: event,
        func: () => queue.workerMethods.runWebhooksHandlersEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers_webhooks`,
        timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
        teamId: event.teamId,
    })
}

const TOPIC_PROCESSING_DELAY: Record<string, number> = {
    [KAFKA_ON_EVENT_RETRIES_1]: 60000,
    [KAFKA_ON_EVENT_RETRIES_2]: 60000,
}

export async function eachBatchAppsOnEventHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    // Get the first message from the batch, and use the topic to determine the
    // delay for this batch. This allows us to delay the processing of the batch
    // until the retry delay has passed.
    const firstMessage = payload.batch.messages[0]
    const delay = TOPIC_PROCESSING_DELAY[payload.batch.topic]
    if (delay) {
        const now = Date.now()
        const messageTimestamp = new Date(firstMessage.timestamp).getTime()
        const messageDelay = now - messageTimestamp
        if (messageDelay < delay) {
            const waitTime = delay - messageDelay
            payload.pause()
            setTimeout(() => payload.resume(), waitTime)
        }
    }

    await eachBatch(payload, queue, eachMessageAppsOnEventHandlers, groupIntoBatches, 'async_handlers_on_event')
}

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageWebhooksHandlers, groupIntoBatches, 'async_handlers_webhooks')
}
