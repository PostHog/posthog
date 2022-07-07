import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { status } from '../../../utils/status'
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
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isStale, isRunning }: EachBatchPayload,
    queue: KafkaQueue
): Promise<void> {
    if (batch.messages.length === 0 || !isRunning() || isStale()) {
        status.info('🚪', `Bailing out of a batch of ${batch.messages.length} buffer events`, {
            isRunning: isRunning(),
            isStale: isStale(),
        })
        await heartbeat()
        return
    }

    const batchStartTimer = new Date()

    /** First message to be processed post-sleep. Undefined means there's no sleep needed. */
    let cutoffMessage: KafkaMessage | undefined
    /** How long should we sleep for until we have a desired delay in processing. */
    let consumerSleepMs = 0
    for (const message of batch.messages) {
        // Kafka timestamps are Unix timestamps in string format
        const processAt = Number(message.timestamp) + queue.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
        const delayUntilTimeToProcess = processAt - Date.now()

        if (delayUntilTimeToProcess <= 0 && !cutoffMessage) {
            await eachMessageBuffer(message, resolveOffset, heartbeat, queue)
        } else {
            if (!cutoffMessage) {
                cutoffMessage = message
            }
            if (delayUntilTimeToProcess > consumerSleepMs) {
                consumerSleepMs = delayUntilTimeToProcess
            }
        }
    }
    await commitOffsetsIfNecessary()
    if (cutoffMessage) {
        // Pause the consumer for this partition until we can process all unprocessed messages from this batch
        // This will also seek within the partition to the offset of the cutoff message
        queue.pluginsServer.statsd?.gauge('buffer_sleep', consumerSleepMs, { partition: String(batch.partition) })
        await queue.bufferSleep(consumerSleepMs, batch.partition, cutoffMessage.offset, heartbeat)
    }

    queue.pluginsServer.statsd?.timing('kafka_queue.each_batch_buffer', batchStartTimer)
}
