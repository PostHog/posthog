import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import { runInstrumentedFunction } from 'main/utils'

import { Hub, WorkerMethods } from '../../../types'
import { status } from '../../../utils/status'
import { groupIntoBatches, sanitizeEvent } from '../../../utils/utils'
import { KafkaQueue } from '../kafka-queue'
import { eachBatch } from './utils'

export async function eachMessageAsyncHandlers(message: KafkaMessage, queue: KafkaQueue): Promise<void> {
    const event = JSON.parse(message.value!.toString())
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
