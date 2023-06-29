import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { RawClickHouseEvent } from '../../../types'
import { status } from '../../../utils/status'
import { getPluginMethodsForTeam } from '../../../worker/plugins/run'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export async function eachBatch(
    /**
     * Using the provided groupIntoBatches function, split the incoming batch into micro-batches
     * that are executed **sequentially**, committing offsets after each of them.
     * Events within a single micro-batch are processed in parallel.
     */
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: KafkaJSIngestionConsumer,
    eachMessage: (message: KafkaMessage, queue: KafkaJSIngestionConsumer) => Promise<void>,
    groupIntoBatches: (messages: KafkaMessage[], batchSize: number) => KafkaMessage[][],
    key: string
): Promise<void> {
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    const transaction = Sentry.startTransaction({ name: `eachBatch(${eachMessage.name})` }, { topic: queue.topic })

    try {
        // Before we group into batches, check which messages actually need to
        // be processed i.e. which have onEvent handlers associated with the
        // team_id. We have to pass the message value first, which is going to
        // double up some work, but it should save some time in terms of
        // better parallelism in batches.
        //
        // Ultimately, we should get the [message, onEvent App] pairs and push
        // these to a separate topic, but that's a bit more work than we want
        // to do right now.
        //
        // However, if we did do this, we would be able to, e.g. provide retry
        // topics for each destination and thereby avoid blocking the consumer.
        //
        // Note that the below is nowhere near as efficient as it could be,
        // consider that the filtering on events is handled within the onEvent
        // function. Either we need to move that filtering to here, or we need
        // provide stream rather than batch processing to get improved
        // parallelism. That shouldn't be so tricky but it involves a bit of
        // playing with tracking offsets.
        const teamMessagePairs = batch.messages.map(
            (message) =>
                [(JSON.parse(message.value!.toString()) as RawClickHouseEvent).team_id, message] as [
                    number,
                    KafkaMessage
                ]
        )

        // Filter out events that fon't have `onEvent` associated
        const teamMessagePairsWithOnEvent = await Promise.all(
            teamMessagePairs.filter(async ([teamId, _]) => {
                const onEventApps = await getPluginMethodsForTeam(queue.pluginsServer, teamId, 'onEvent')
                return onEventApps.length > 0
            })
        )

        const messageBatches = groupIntoBatches(
            teamMessagePairsWithOnEvent.map(([_, message]) => message),
            queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER
        )
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, { key: key })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', messageBatches.length, { key: key })

        for (const messageBatch of messageBatches) {
            const batchSpan = transaction.startChild({ op: 'messageBatch', data: { batchLength: messageBatch.length } })

            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                await heartbeat()
                return
            }

            const lastBatchMessage = messageBatch[messageBatch.length - 1]
            await Promise.all(
                messageBatch.map((message: KafkaMessage) => eachMessage(message, queue).finally(() => heartbeat()))
            )

            // this if should never be false, but who can trust computers these days
            if (lastBatchMessage) {
                resolveOffset(lastBatchMessage.offset)
            }
            await commitOffsetsIfNecessary()

            // Record that latest messages timestamp, such that we can then, for
            // instance, alert on if this value is too old.
            latestOffsetTimestampGauge
                .labels({ partition: batch.partition, topic: batch.topic, groupId: key })
                .set(Number.parseInt(lastBatchMessage.timestamp))

            await heartbeat()

            batchSpan.finish()
        }

        status.debug(
            '🧩',
            `Kafka batch of ${batch.messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        queue.pluginsServer.statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
        transaction.finish()
    }
}
