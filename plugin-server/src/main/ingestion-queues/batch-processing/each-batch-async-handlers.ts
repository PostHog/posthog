import { Message } from 'node-rdkafka-acosom'

import { RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { IngestionConsumer } from '../kafka-queue'
import { eachBatch } from './each-batch'

export async function eachMessageAsyncHandlers(message: Message, queue: IngestionConsumer): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        server: queue.pluginsServer,
        event: event,
        func: () => queue.workerMethods.runAsyncHandlersEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers`,
        timeoutMessage: 'After 30 seconds still running runAsyncHandlersEventPipeline',
    })
}

export async function eachBatchAsyncHandlers(messages: Message[], queue: IngestionConsumer): Promise<void> {
    await eachBatch(messages, queue, eachMessageAsyncHandlers, groupIntoBatches, 'async_handlers')
}
