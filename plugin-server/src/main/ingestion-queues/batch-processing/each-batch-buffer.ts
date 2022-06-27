import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { runInstrumentedFunction } from '../../utils'
import { KafkaQueue } from '../kafka-queue'

export async function eachMessageBuffer(
    message: KafkaMessage,
    resolveOffset: EachBatchPayload['resolveOffset'],
    heartbeat: EachBatchPayload['heartbeat'],
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
    await heartbeat()
}

export async function eachBatchBuffer(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary }: EachBatchPayload,
    queue: KafkaQueue
): Promise<void> {
    if (batch.messages.length === 0) {
        return
    }
    const batchStartTimer = new Date()

    /** Index of first message to be processed post-sleep. -1 means there's no sleep needed. */
    let messagesCutoffIndex = -1
    /** How long should we sleep for until we have a desired delay in processing. */
    let consumerSleepMs = 0
    for (let i = 0; i < batch.messages.length; i++) {
        const message = batch.messages[i]
        // Kafka timestamps are Unix timestamps in string format
        const processAt = Number(message.timestamp) + queue.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
        const delayUntilTimeToProcess = processAt - Date.now()

        if (delayUntilTimeToProcess <= 0 && messagesCutoffIndex < 0) {
            await eachMessageBuffer(message, resolveOffset, heartbeat, queue)
        } else {
            if (messagesCutoffIndex < 0) {
                messagesCutoffIndex = i
            }
            if (delayUntilTimeToProcess > consumerSleepMs) {
                consumerSleepMs = delayUntilTimeToProcess
            }
        }
    }
    await commitOffsetsIfNecessary()
    if (messagesCutoffIndex >= 0) {
        // Pause the consumer for this partition until we can process all unprocessed messages from this batch
        await queue.bufferSleep(consumerSleepMs, batch.partition, heartbeat)
        for (const message of batch.messages.slice(messagesCutoffIndex)) {
            await eachMessageBuffer(message, resolveOffset, heartbeat, queue)
        }
    }
    await commitOffsetsIfNecessary()

    queue.pluginsServer.statsd?.timing('kafka_queue.each_batch_buffer', batchStartTimer)
}
