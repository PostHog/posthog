import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { KafkaQueue } from '../kafka-queue'

export async function eachBatch(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: KafkaQueue,
    eachMessage: (message: KafkaMessage, queue: KafkaQueue) => Promise<void>,
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    try {
        const messageBatches = groupIntoBatches(
            batch.messages,
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )

        for (const messageBatch of messageBatches) {
            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                return
            }

            await Promise.all(messageBatch.map((message) => eachMessage(message, queue)))

            // this if should never be false, but who can trust computers these days
            if (messageBatch.length > 0) {
                resolveOffset(messageBatch[messageBatch.length - 1].offset)
            }
            await commitOffsetsIfNecessary()
            await heartbeat()
        }

        status.info(
            '🧩',
            `Kafka batch of ${batch.messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        queue.pluginsServer.statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
    }
}
