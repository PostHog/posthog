import { Message } from 'node-rdkafka-acosom'

import { status } from '../../../utils/status'
import { IngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'

export async function eachBatch(
    messages: Message[],
    queue: IngestionConsumer,
    eachMessage: (message: Message, queue: IngestionConsumer) => Promise<void>,
    groupIntoBatches: (messages: Message[], batchSize: number) => Message[][],
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    try {
        const messageBatches = groupIntoBatches(
            messages,
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', messages.length, { key: key })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', messageBatches.length, { key: key })

        for (const messageBatch of messageBatches) {
            await Promise.all(messageBatch.map((message: Message) => eachMessage(message, queue)))

            // Record that latest messages timestamp, such that we can then, for
            // instance, alert on if this value is too old.
            for (const message of messageBatch) {
                if (message.timestamp) {
                    latestOffsetTimestampGauge
                        .labels({ partition: message.partition, topic: message.topic, groupId: key })
                        .set(message.timestamp)
                }
            }
        }

        status.debug(
            '🧩',
            `Kafka batch of ${messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        queue.pluginsServer.statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
    }
}
