import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: KafkaJSIngestionConsumer): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        server: queue.pluginsServer,
        event: event,
        func: () => queue.workerMethods.runAsyncHandlersEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers`,
        timeoutMessage: 'After 30 seconds still running runAsyncHandlersEventPipeline',
        teamId: event.teamId,
    })
}

export async function eachBatchAsyncHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageAsyncHandlers, groupIntoBatches, 'async_handlers')
}
