import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { status } from '../../../utils/status'
import { KafkaQueue } from '../kafka-queue'

export async function eachBatch(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: KafkaQueue,
    eachMessage: (message: KafkaMessage, queue: KafkaQueue) => Promise<void>,
    groupIntoBatches: (messages: KafkaMessage[], batchSize: number) => KafkaMessage[][],
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    async function tryHeartBeat(): Promise<void> {
        try {
            await heartbeat()
        } catch (error) {
            if (error.type === 'UNKNOWN_MEMBER_ID') {
                queue.pluginsServer.statsd?.increment('kafka_queue_heartbeat_failure_coordinator_not_aware')
            } else {
                // This will reach sentry
                throw error
            }
        }
    }

    try {
        const messageBatches = groupIntoBatches(
            batch.messages,
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )
        queue.pluginsServer.statsd?.gauge('ingest_event_batching.input_length', batch.messages.length, { key: key })
        queue.pluginsServer.statsd?.gauge('ingest_event_batching.batch_count', messageBatches.length, { key: key })

        for (const messageBatch of messageBatches) {
            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                await tryHeartBeat()
                return
            }

            await Promise.all(messageBatch.map((message: KafkaMessage) => eachMessage(message, queue)))

            // this if should never be false, but who can trust computers these days
            if (messageBatch.length > 0) {
                resolveOffset(messageBatch[messageBatch.length - 1].offset)
            }
            await commitOffsetsIfNecessary()
            await tryHeartBeat()
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
