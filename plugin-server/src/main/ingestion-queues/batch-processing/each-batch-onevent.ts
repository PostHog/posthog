import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import { Counter } from 'prom-client'

import { PostIngestionEvent, RawKafkaEvent } from '../../../types'
import { convertToPostIngestionEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import {
    processComposeWebhookStep,
    processOnEventStep,
} from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter, latestOffsetTimestampGauge } from '../metrics'
import { ingestEventBatchingBatchCountSummary, ingestEventBatchingInputLengthSummary } from './metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export const silentFailuresAsyncHandlers = new Counter({
    name: 'async_handlers_silent_failure',
    help: 'Number silent failures from async handlers.',
})
// exporting only for testing
export function groupIntoBatchesByUsage(
    array: KafkaMessage[],
    batchSize: number,
    shouldProcess: (teamId: number) => boolean
): { eventBatch: RawKafkaEvent[]; lastOffset: string; lastTimestamp: string }[] {
    const result: { eventBatch: RawKafkaEvent[]; lastOffset: string; lastTimestamp: string }[] = []
    let currentBatch: RawKafkaEvent[] = []
    let currentCount = 0
    array.forEach((message, index) => {
        const clickHouseEvent = JSON.parse(message.value!.toString()) as RawKafkaEvent
        if (shouldProcess(clickHouseEvent.team_id)) {
            currentBatch.push(clickHouseEvent)
            currentCount++
        } else {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics-webhook',
                    drop_cause: 'no_matching_action',
                })
                .inc()
        }
        if (currentCount === batchSize || index === array.length - 1) {
            result.push({ eventBatch: currentBatch, lastOffset: message.offset, lastTimestamp: message.timestamp })
            currentBatch = []
            currentCount = 0
        }
    })
    return result
}

export async function eachBatchHandlerHelper(
    payload: EachBatchPayload,
    shouldProcess: (teamId: number) => boolean,
    eachMessageHandler: (event: RawKafkaEvent) => Promise<void>,
    concurrency: number,
    stats_key: string
): Promise<void> {
    // similar to eachBatch function in each-batch.ts, but without the dependency on the KafkaJSIngestionConsumer
    // & handling the different batching return type
    const key = `async_handlers_${stats_key}`
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`
    const { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload = payload

    const transaction = Sentry.startTransaction({ name: `eachBatch${stats_key}` })

    try {
        const batchesWithOffsets = groupIntoBatchesByUsage(batch.messages, concurrency, shouldProcess)

        ingestEventBatchingInputLengthSummary.observe(batch.messages.length)
        ingestEventBatchingBatchCountSummary.observe(batchesWithOffsets.length)

        for (const { eventBatch, lastOffset, lastTimestamp } of batchesWithOffsets) {
            const batchSpan = transaction.startChild({ op: 'messageBatch', data: { batchLength: eventBatch.length } })

            if (!isRunning() || isStale()) {
                status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                    isRunning: isRunning(),
                    isStale: isStale(),
                    msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                })
                await heartbeat()
                return
            }

            await Promise.all(
                eventBatch.map((event: RawKafkaEvent) => eachMessageHandler(event).finally(() => heartbeat()))
            )

            resolveOffset(lastOffset)
            await commitOffsetsIfNecessary()

            // Record that latest messages timestamp, such that we can then, for
            // instance, alert on if this value is too old.
            latestOffsetTimestampGauge
                .labels({ partition: batch.partition, topic: batch.topic, groupId: key })
                .set(Number.parseInt(lastTimestamp))

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
        transaction.finish()
    }
}

export async function handleOnEventPlugins(event: PostIngestionEvent, queue: KafkaJSIngestionConsumer): Promise<void> {
    await runInstrumentedFunction({
        func: () => processOnEventStep(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function handleComposeWebhookPlugins(
    event: PostIngestionEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await runInstrumentedFunction({
        func: () => processComposeWebhookStep(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function eachMessageAppsOnEventHandlers(
    clickHouseEvent: RawKafkaEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const pluginConfigs = queue.pluginsServer.pluginConfigsPerTeam.get(clickHouseEvent.team_id)
    if (pluginConfigs) {
        const event = convertToPostIngestionEvent(clickHouseEvent)
        await Promise.all([handleOnEventPlugins(event, queue), handleComposeWebhookPlugins(event, queue)])
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
    await eachBatchHandlerHelper(
        payload,
        (teamId) => queue.pluginsServer.pluginConfigsPerTeam.has(teamId),
        (event) => eachMessageAppsOnEventHandlers(event, queue),
        queue.pluginsServer.TASKS_PER_WORKER,
        'on_event'
    )
}
