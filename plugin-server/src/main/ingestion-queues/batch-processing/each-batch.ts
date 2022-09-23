import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { status } from '../../../utils/status'
import { KafkaQueue } from '../kafka-queue'

export class KafkaSkipCommitError extends Error {}

export async function eachBatch(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: KafkaQueue,
    eachMessage: (message: KafkaMessage, queue: KafkaQueue) => Promise<void>,
    groupIntoBatches: (messages: KafkaMessage[], batchSize: number) => KafkaMessage[][],
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    try {
        const messageBatches = groupIntoBatches(
            batch.messages,
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, { key: key })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', messageBatches.length, { key: key })

        for (const messageBatch of messageBatches) {
            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                await heartbeat()
                return
            }

            try {
                await Promise.all(messageBatch.map((message: KafkaMessage) => eachMessage(message, queue)))

                // this if should never be false, but who can trust computers these days
                if (messageBatch.length > 0) {
                    resolveOffset(messageBatch[messageBatch.length - 1].offset)
                }

                await commitOffsetsIfNecessary()
            } catch (error) {
                /*
                On KafkaSkipCommitError we want to keep the consumer running as we've encountered an issue downstream which we expect 
                to resolve with time e.g. Postgres down. Thus in this case we don't want to crashloop the server as it may also be processing 
                other things like jobs.

                However, errors thrown that were not explicitly thrown by us (i.e. not KafkaSkipCommitError) _should_ cause the consumer and server to crash.
                They probably indicate that either we broke something or Kafka is unavailable/behaving erratically.
                */
                if (!(error instanceof KafkaSkipCommitError)) {
                    throw error
                }
            } finally {
                await heartbeat()
            }
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
