import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { ClickhouseEventKafka } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { runInstrumentedFunction } from '../../utils'
import { KafkaQueue } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: KafkaQueue): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as ClickhouseEventKafka
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        server: queue.pluginsServer,
        event: event,
        func: () => queue.workerMethods.runAsyncHandlersEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers`,
        timeoutMessage: 'After 30 seconds still running runAsyncHandlersEventPipeline',
    })
}

export async function eachBatchAsyncHandlers(payload: EachBatchPayload, queue: KafkaQueue): Promise<void> {
    await eachBatch(payload, queue, eachMessageAsyncHandlers, 'async_handlers')
}
