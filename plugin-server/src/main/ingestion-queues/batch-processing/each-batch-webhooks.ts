import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import { Counter } from 'prom-client'
import { ActionMatcher } from 'worker/ingestion/action-matcher'

import { PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { convertToIngestionEvent, convertToProcessedPluginEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { HookCommander } from '../../../worker/ingestion/hooks'
import { runInstrumentedFunction } from '../../utils'
import { eventDroppedCounter, latestOffsetTimestampGauge } from '../metrics'

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
): { eventBatch: RawClickHouseEvent[]; lastOffset: string; lastTimestamp: string }[] {
    // Most events will not trigger a webhook call, so we want to filter them out as soon as possible
    // to achieve the highest effective concurrency when executing the actual HTTP calls.
    // actionMatcher holds an in-memory set of all teams with enabled webhooks, that we use to
    // drop events based on that signal. To use it we must parse the message, as there aren't that many
    // webhooks, we can keep batches of the parsed messages in memory with the offsets of the last message
    const result: { eventBatch: RawClickHouseEvent[]; lastOffset: string; lastTimestamp: string }[] = []
    let currentBatch: RawClickHouseEvent[] = []
    let currentCount = 0
    array.forEach((message, index) => {
        const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
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

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    statsd: StatsD | undefined,
    concurrency: number
): Promise<void> {
    await eachBatchHandlerHelper(
        payload,
        (teamId) => actionMatcher.hasWebhooks(teamId),
        (event) => eachMessageWebhooksHandlers(event, actionMatcher, hookCannon, statsd),
        statsd,
        concurrency,
        'webhooks'
    )
}

export async function eachBatchHandlerHelper(
    payload: EachBatchPayload,
    shouldProcess: (teamId: number) => boolean,
    eachMessageHandler: (event: RawClickHouseEvent) => Promise<void>,
    statsd: StatsD | undefined,
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

        statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, { key: key })
        statsd?.histogram('ingest_event_batching.batch_count', batchesWithOffsets.length, { key: key })

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
                eventBatch.map((event: RawClickHouseEvent) => eachMessageHandler(event).finally(() => heartbeat()))
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
        statsd?.timing(`kafka_queue.${loggingKey}`, batchStartTimer)
        transaction.finish()
    }
}

export async function eachMessageWebhooksHandlers(
    clickHouseEvent: RawClickHouseEvent,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    statsd: StatsD | undefined
): Promise<void> {
    if (!actionMatcher.hasWebhooks(clickHouseEvent.team_id)) {
        // exit early if no webhooks nor resthooks
        return
    }
    const event = convertToIngestionEvent(clickHouseEvent)

    // TODO: previously onEvent and Webhooks were executed in the same process,
    // and onEvent would call convertToProcessedPluginEvent, which ends up
    // mutating the `event` that is passed in. To ensure that we have the same
    // behaviour we run this here, but we should probably refactor this to
    // ensure that we don't mutate the event.
    convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        func: () => runWebhooks(statsd, actionMatcher, hookCannon, event),
        statsKey: `kafka_queue.process_async_handlers_webhooks`,
        timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

async function runWebhooks(
    statsd: StatsD | undefined,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    event: PostIngestionEvent
) {
    const timer = new Date()

    try {
        statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'webhooks' })
        await processWebhooksStep(event, actionMatcher, hookCannon)
        statsd?.increment('kafka_queue.webhooks.processed')
        statsd?.increment('kafka_queue.event_pipeline.step', { step: processWebhooksStep.name })
        statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: processWebhooksStep.name })
    } catch (error) {
        statsd?.increment('kafka_queue.event_pipeline.step.error', { step: processWebhooksStep.name })

        if (error instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            status.error('Error processing webhooks', {
                stack: error.stack,
                eventUuid: event.eventUuid,
                teamId: event.teamId,
                error: error,
            })
            throw error
        }

        status.warn(`⚠️`, 'Error processing webhooks, silently moving on', {
            stack: error.stack,
            eventUuid: event.eventUuid,
            teamId: event.teamId,
            error: error,
        })
        silentFailuresAsyncHandlers.inc()
    }
}
