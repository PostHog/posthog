import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter, latestOffsetTimestampGauge } from '../metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export async function eachMessageAppsOnEventHandlers(
    message: KafkaMessage,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent

    const pluginConfigs = queue.pluginsServer.pluginConfigsPerTeam.get(clickHouseEvent.team_id)
    if (pluginConfigs) {
        // Elements parsing can be extremely slow, so we skip it for some plugins
        const skipElementsChain = pluginConfigs.every((pluginConfig) =>
            process.env.SKIP_ELEMENTS_PARSING_PLUGINS?.split(',').includes(pluginConfig.plugin_id.toString())
        )

        const event = convertToIngestionEvent(clickHouseEvent, skipElementsChain)
        await runInstrumentedFunction({
            event: event,
            func: () => queue.workerMethods.runAppsOnEventPipeline(event),
            statsKey: `kafka_queue.process_async_handlers_on_event`,
            timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
            teamId: event.teamId,
        })
    } else {
        eventDroppedCounter
            .labels({
                event_type: 'onevent',
                drop_cause: 'no_matching_plugin',
            })
            .inc()
    }
}

export async function eachBatchAppsOnEventHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageAppsOnEventHandlers, groupIntoBatches, 'async_handlers_on_event')
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
