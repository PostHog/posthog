import { RetryError } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KAFKA_EVENTS_JSON, KAFKA_ON_EVENT_RETRIES_1, KAFKA_ON_EVENT_RETRIES_2 } from '../../../config/kafka-topics'
import { Hub, RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent, convertToProcessedPluginEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const RETRY_TOPICS_LOOKUP = {
    [KAFKA_EVENTS_JSON]: KAFKA_ON_EVENT_RETRIES_1,
    [KAFKA_ON_EVENT_RETRIES_1]: KAFKA_ON_EVENT_RETRIES_2,
}

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
        const messageBatches = groupIntoBatches(
            batch.messages,
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
                messageBatch.map(async (message: KafkaMessage) => {
                    try {
                        const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
                        const event = convertToIngestionEvent(clickHouseEvent)
                        const eventWithTeam = convertToProcessedPluginEvent(event)
                        const pluginMethodsToRun = getPluginMethodsForTeam(queue.pluginsServer, eventWithTeam.team_id, 'onEvent')
                        return await eachMessage(message, queue).finally(() => heartbeat())
                    }
                    catch (error) {
                        if (error instanceof RetryError) {
                            // TODO: await for Kafka responses in batches
                            const nextQueue = RETRY_TOPICS_LOOKUP[batch.topic]
                            if (!nextQueue) {
                                await queue.pluginsServer.kafkaProducer.queueMessage({ topic: nextQueue, messages: [{ ...message, }] })
                            } else {
                                status.error('🔥', `Failed to retry message on ${nextQueue}`, { error })
                            }
                        }
                    }
                })
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
            `Kafka batch of ${batch.messages.length} events completed in ${new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        queue.pluginsServer.statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
        transaction.finish()
    }
}
function getPluginMethodsForTeam(pluginsServer: Hub, team_id: number, arg2: string) {
    throw new Error('Function not implemented.')
}

