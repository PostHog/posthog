import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { runInstrumentedFunction } from '../utils'
import { IngestionQueue } from './ingestion-queue'

class DelayProcessing extends Error {}

export async function eachMessageBuffer(
    message: KafkaMessage,
    resolveOffset: EachBatchPayload['resolveOffset'],
    ingestionQueue: IngestionQueue
): Promise<void> {
    const bufferEvent = JSON.parse(message.value!.toString())
    await runInstrumentedFunction({
        server: ingestionQueue.pluginsServer,
        event: bufferEvent,
        func: () => ingestionQueue.workerMethods.runBufferEventPipeline(bufferEvent),
        statsKey: `kafka_queue.ingest_buffer_event`,
        timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
    })
    resolveOffset(message.offset)
}

export async function eachBatchBuffer(
    { batch, resolveOffset, commitOffsetsIfNecessary }: EachBatchPayload,
    ingestionQueue: IngestionQueue
): Promise<void> {
    if (batch.messages.length === 0) {
        return
    }
    const batchStartTimer = new Date()

    let consumerSleep = 0
    for (const message of batch.messages) {
        // kafka timestamps are unix timestamps in string format
        const processAt = Number(message.timestamp) + ingestionQueue.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
        const delayUntilTimeToProcess = processAt - Date.now()

        if (delayUntilTimeToProcess < 0) {
            await eachMessageBuffer(message, resolveOffset, ingestionQueue)
        } else {
            consumerSleep = Math.max(consumerSleep, delayUntilTimeToProcess)
        }
    }

    // if consumerSleep > 0 it means we didn't process at least one message
    if (consumerSleep > 0) {
        // pause the consumer for this partition until we can process all unprocessed messages from this batch
        ingestionQueue.sleepTimeout = setTimeout(() => {
            if (ingestionQueue.sleepTimeout) {
                clearTimeout(ingestionQueue.sleepTimeout)
            }
            ingestionQueue.resume(batch.topic, batch.partition)
        }, consumerSleep)
        await ingestionQueue.pause(batch.topic, batch.partition)

        // we throw an error to prevent the non-processed message offsets from being committed
        // from the kafkajs docs:
        // > resolveOffset() is used to mark a message in the batch as processed.
        // > In case of errors, the consumer will automatically commit the resolved offsets.
        throw new DelayProcessing()
    }

    await commitOffsetsIfNecessary()

    ingestionQueue.pluginsServer.statsd?.timing('kafka_queue.each_batch_buffer', batchStartTimer)
}
