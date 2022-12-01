import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    // If the message isn't well formed JSON, just skip it. Ideally we'd send to a DLQ but I'll leave that as a TODO.
    // TODO: Send to DLQ on message malformed
    let clickHouseEvent: RawClickHouseEvent
    let event: PostIngestionEvent
    if (!message.value) {
        return
    } else {
        try {
            clickHouseEvent = JSON.parse(message.value.toString())
            event = convertToIngestionEvent(clickHouseEvent)
        } catch (error) {
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
