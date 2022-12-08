import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    let clickHouseEvent: RawClickHouseEvent
    let event: PostIngestionEvent

    if (!message.value) {
        return
    } else {
        try {
            // If the message isn't well formed JSON, just skip it. Ideally we'd
            // send to a DLQ but I'll leave that as a TODO.
            // TODO: Send to DLQ on message malformed.
            // NOTE: prior to adding the try/catch here, if there was an error
            // when parsing and converting the event would result in the error
            // being raised to KafkaJS, thus causing the offset to not be
            // committed. i.e. we didn't handle poison messages correctly.
            clickHouseEvent = JSON.parse(message.value.toString())
            event = convertToIngestionEvent(clickHouseEvent)
        } catch (error) {
            Sentry.captureException(error, { extra: { clickHouseEvent } })
            return
        }
    }

    await runInstrumentedFunction({
        server: queue.pluginsServer,
        event: event,
        func: () => queue.workerMethods.runAsyncHandlersEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers`,
        timeoutMessage: 'After 30 seconds still running runAsyncHandlersEventPipeline',
    })
}

export async function eachBatchAsyncHandlers(payload: EachBatchPayload, queue: IngestionConsumer): Promise<void> {
    await eachBatch(payload, queue, eachMessageAsyncHandlers, groupIntoBatches, 'async_handlers')
}
