import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { status } from '../../../utils/status'
import { IngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export async function eachBatch(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: IngestionConsumer,
    eachMessage: (message: KafkaMessage, queue: IngestionConsumer) => Promise<void>,
    groupIntoBatches: (messages: KafkaMessage[], batchSize: number) => KafkaMessage[][],
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    const transaction = Sentry.startTransaction({ name: `eachBatch(${eachMessage.name})` }, { topic: queue.topic })

    try {
        const messageBatches = groupIntoBatches(
            batch.messages,
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, { key: key })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', messageBatches.length, { key: key })

        for (const messageBatch of messageBatches) {
            const batchSpan = transaction.startChild({ op: 'messageBatch', data: { batchLength: messageBatch.length } })

            const processingPromises = messageBatch.map((message: KafkaMessage) => eachMessage(message, queue))
            processingPromises.push(heartbeat()) // Signal to the Kafka cluster that we are actively processing events
            await Promise.all(processingPromises)

            batchSpan.finish()
        }

        // Commit offsets once at the end of the batch. We run the risk of duplicates
        // if the pod is prematurely killed in the middle of a batch, but this allows
        // us to process events out of order within a batch, for higher throughput.
        const commitSpan = transaction.startChild({ op: 'offsetCommit' })
        const lastMessage = batch.messages.at(-1)
        if (lastMessage) {
            resolveOffset(lastMessage.offset)
            await commitOffsetsIfNecessary()
            latestOffsetTimestampGauge
                .labels({ partition: batch.partition, topic: batch.topic, groupId: key })
                .set(Number.parseInt(lastMessage.timestamp))
        }
        commitSpan.finish()

        status.debug(
            '🧩',
            `Kafka batch of ${batch.messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )

        if (!isRunning() || isStale()) {
            status.info('🚪', `Ending the consumer loop`, {
                isRunning: isRunning(),
                isStale: isStale(),
                msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
            })
            await heartbeat()
            return
        }
    } finally {
        queue.pluginsServer.statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
        transaction.finish()
    }
}
