import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { runInstrumentedFunction } from '../../utils'
import { KafkaQueue } from '../kafka-queue'

class DelayProcessing extends Error {}

export async function eachMessageBuffer(
    message: KafkaMessage,
    resolveOffset: EachBatchPayload['resolveOffset'],
    queue: KafkaQueue
): Promise<void> {
    const bufferEvent = JSON.parse(message.value!.toString())
    await runInstrumentedFunction({
        server: queue.pluginsServer,
        event: bufferEvent,
        func: () => queue.workerMethods.runBufferEventPipeline(bufferEvent),
        statsKey: `kafka_queue.ingest_buffer_event`,
        timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
    })
    resolveOffset(message.offset)
}

export async function eachBatchBuffer(
    { batch, resolveOffset, commitOffsetsIfNecessary }: EachBatchPayload,
    queue: KafkaQueue
): Promise<void> {
    if (batch.messages.length === 0) {
        return
    }
    const batchStartTimer = new Date()

    let consumerSleepMs = 0
    for (const message of batch.messages) {
        // kafka timestamps are unix timestamps in string format
        const processAt = Number(message.timestamp) + queue.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
        const delayUntilTimeToProcess = processAt - Date.now()

        if (delayUntilTimeToProcess < 0) {
            await eachMessageBuffer(message, resolveOffset, queue)
        } else {
            consumerSleepMs = Math.max(consumerSleepMs, delayUntilTimeToProcess)
        }
    }

    // if consumerSleep > 0 it means we didn't process at least one message
    if (consumerSleepMs > 0) {
        // pause the consumer for this partition until we can process all unprocessed messages from this batch
        await queue.bufferSleep(consumerSleepMs, batch.partition)

        // we throw an error to prevent the non-processed message offsets from being committed
        // from the kafkajs docs:
        // > resolveOffset() is used to mark a message in the batch as processed.
        // > In case of errors, the consumer will automatically commit the resolved offsets.
        throw new DelayProcessing()
    }

    await commitOffsetsIfNecessary()

    queue.pluginsServer.statsd?.timing('kafka_queue.each_batch_buffer', batchStartTimer)
}
