import * as Sentry from '@sentry/node'
import { Message, MessageHeader } from 'node-rdkafka'

import { KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../config/kafka-topics'
import { PipelineEvent, ValueMatcher } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { retryIfRetriable } from '../../../utils/retries'
import { status } from '../../../utils/status'
import { ConfiguredLimiter, LoggingLimiter, OverflowWarningLimiter } from '../../../utils/token-bucket'
import { EventPipelineRunner } from '../../../worker/ingestion/event-pipeline/runner'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { ingestionPartitionKeyOverflowed } from '../analytics-events-ingestion-consumer'
import { IngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter, latestOffsetTimestampGauge } from '../metrics'
import {
    ingestEventBatchingBatchCountSummary,
    ingestEventBatchingInputLengthSummary,
    ingestionOverflowingMessagesTotal,
    ingestionParallelism,
    ingestionParallelismPotential,
    kafkaBatchOffsetCommitted,
    kafkaBatchStart,
} from './metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export enum IngestionOverflowMode {
    Disabled,
    Reroute,
    ConsumeSplitByDistinctId,
    ConsumeSplitEvenly,
}

type IngestionSplitBatch = {
    toProcess: { message: Message; pluginEvent: PipelineEvent }[][]
    toOverflow: Message[]
}

// Subset of EventPipelineResult to make sure we don't access what's exported for the tests
type IngestResult = {
    // Promises that the batch handler should await on before committing offsets,
    // contains the Kafka producer ACKs, to avoid blocking after every message.
    promises?: Array<Promise<void>>
}

async function handleProcessingError(
    error: any,
    message: Message,
    pluginEvent: PipelineEvent,
    queue: IngestionConsumer
) {
    status.error('🔥', `Error processing message`, {
        stack: error.stack,
        error: error,
    })

    // If the error is a non-retriable error, push to the dlq and commit the offset. Else raise the
    // error.
    //
    // NOTE: there is behavior to push to a DLQ at the moment within EventPipelineRunner. This
    // doesn't work so well with e.g. messages that when sent to the DLQ is it's self too large.
    // Here we explicitly do _not_ add any additional metadata to the message. We might want to add
    // some metadata to the message e.g. in the header or reference e.g. the sentry event id.
    //
    // TODO: property abstract out this `isRetriable` error logic. This is currently relying on the
    // fact that node-rdkafka adheres to the `isRetriable` interface.
    if (error?.isRetriable === false) {
        const sentryEventId = Sentry.captureException(error)
        const headers: MessageHeader[] = message.headers ?? []
        headers.push({ ['sentry-event-id']: sentryEventId })
        headers.push({ ['event-id']: pluginEvent.uuid })
        try {
            await queue.pluginsServer.kafkaProducer.produce({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
                value: message.value,
                key: message.key,
                headers: headers,
                waitForAck: true,
            })
        } catch (error) {
            // If we can't send to the DLQ and it's not retriable, just continue. We'll commit the
            // offset and move on.
            if (error?.isRetriable === false) {
                status.error('🔥', `Error pushing to DLQ`, {
                    stack: error.stack,
                    error: error,
                })
                return
            }

            // If we can't send to the DLQ and it is retriable, raise the error.
            throw error
        }
    } else {
        throw error
    }
}

export async function eachBatchParallelIngestion(
    tokenBlockList: ValueMatcher<string>,
    messages: Message[],
    queue: IngestionConsumer,
    overflowMode: IngestionOverflowMode
): Promise<void> {
    const batchStartTimer = new Date()
    const metricKey = 'ingestion'
    const loggingKey = `each_batch_parallel_ingestion`

    const transaction = Sentry.startTransaction({ name: `eachBatchParallelIngestion` }, { topic: queue.topic })

    try {
        /**
         * Micro-batches should be executed from biggest to smallest to enable the best concurrency.
         * We're sorting with biggest last and pop()ing. Ideally, we'd use a priority queue by length
         * and a separate array for single messages, but let's look at profiles before optimizing.
         */
        const prepareSpan = transaction.startChild({ op: 'prepareBatch' })
        const splitBatch = splitIngestionBatch(tokenBlockList, messages, overflowMode)
        splitBatch.toProcess.sort((a, b) => a.length - b.length)

        ingestEventBatchingInputLengthSummary.observe(messages.length)
        ingestEventBatchingBatchCountSummary.observe(splitBatch.toProcess.length)
        prepareSpan.finish()

        const processingPromises: Array<Promise<void>> = []
        async function processMicroBatches(
            batches: { message: Message; pluginEvent: PipelineEvent }[][]
        ): Promise<void> {
            let currentBatch
            let processedBatches = 0
            while ((currentBatch = batches.pop()) !== undefined) {
                const batchSpan = transaction.startChild({
                    op: 'messageBatch',
                    data: { batchLength: currentBatch.length },
                })

                // Process overflow ingestion warnings
                if (
                    (overflowMode == IngestionOverflowMode.ConsumeSplitByDistinctId ||
                        overflowMode == IngestionOverflowMode.ConsumeSplitEvenly) &&
                    currentBatch.length > 0
                ) {
                    const team = await queue.pluginsServer.teamManager.getTeamForEvent(currentBatch[0].pluginEvent)
                    const distinct_id = currentBatch[0].pluginEvent.distinct_id
                    if (team && OverflowWarningLimiter.consume(`${team.id}:${distinct_id}`, 1)) {
                        processingPromises.push(
                            captureIngestionWarning(queue.pluginsServer.db, team.id, 'ingestion_capacity_overflow', {
                                overflowDistinctId: distinct_id,
                            })
                        )
                    }
                }

                // Process every message sequentially, stash promises to await on later
                for (const { message, pluginEvent } of currentBatch) {
                    try {
                        const result = (await retryIfRetriable(async () => {
                            const runner = new EventPipelineRunner(queue.pluginsServer, pluginEvent)
                            return await runner.runEventPipeline(pluginEvent)
                        })) as IngestResult

                        result.promises?.forEach((promise) =>
                            processingPromises.push(
                                promise.catch(async (error) => {
                                    await handleProcessingError(error, message, pluginEvent, queue)
                                })
                            )
                        )
                    } catch (error) {
                        await handleProcessingError(error, message, pluginEvent, queue)
                    }
                }

                processedBatches++
                batchSpan.finish()
            }
            status.debug('🧩', `Stopping worker after processing ${processedBatches} micro-batches`)
            return Promise.resolve()
        }

        /**
         * Process micro-batches in parallel tasks on the main event loop. This will not allow to use more than
         * one core, but will make better use of that core by waiting less on IO. Parallelism is currently
         * limited by the distinct_id constraint we have on the input topic: one consumer batch does not hold
         * a lot of different distinct_ids.
         *
         * Overflow rerouting (mostly waiting on kafka ACKs) is done in an additional task if needed.
         */
        const parallelism = Math.min(splitBatch.toProcess.length, queue.pluginsServer.INGESTION_CONCURRENCY)
        ingestionParallelism
            .labels({
                overflow_mode: IngestionOverflowMode[overflowMode],
            })
            .observe(parallelism)
        ingestionParallelismPotential
            .labels({
                overflow_mode: IngestionOverflowMode[overflowMode],
            })
            .observe(splitBatch.toProcess.length)
        kafkaBatchStart.inc() // just before processing any events
        const tasks = [...Array(parallelism)].map(() => processMicroBatches(splitBatch.toProcess))

        /**
         * Process overflow redirection while the micro-batches move forward.
         * This increases throughput at the risk of duplication if the batch fails and retries.
         */
        if (splitBatch.toOverflow.length > 0) {
            const overflowSpan = transaction.startChild({
                op: 'emitToOverflow',
                data: { eventCount: splitBatch.toOverflow.length },
            })
            processingPromises.push(emitToOverflow(queue, splitBatch.toOverflow))
            overflowSpan.finish()
        }

        await Promise.all(tasks)

        // Await on successful Kafka writes before closing the batch. At this point, messages
        // have been successfully queued in the producer, only broker / network failures could
        // impact the success. Delaying ACKs allows the producer to write in big batches for
        // better throughput and lower broker load.
        const awaitSpan = transaction.startChild({ op: 'awaitACKs', data: { promiseCount: processingPromises.length } })
        await Promise.all(processingPromises)
        awaitSpan.finish()

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: metricKey })
                    .set(message.timestamp)
            }
        }
        kafkaBatchOffsetCommitted.inc() // successfully processed batch, consumer will commit offsets

        status.debug(
            '🧩',
            `Kafka batch of ${messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        transaction.finish()
    }
}

function computeKey(pluginEvent: PipelineEvent): string {
    return `${pluginEvent.team_id ?? pluginEvent.token}:${pluginEvent.distinct_id}`
}

async function emitToOverflow(queue: IngestionConsumer, kafkaMessages: Message[]) {
    ingestionOverflowingMessagesTotal.inc(kafkaMessages.length)
    await Promise.all(
        kafkaMessages.map((message) =>
            queue.pluginsServer.kafkaProducer.produce({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                value: message.value,
                key: null, // No locality guarantees in overflow
                headers: message.headers,
                waitForAck: true,
            })
        )
    )
}

export function splitIngestionBatch(
    tokenBlockList: ValueMatcher<string>,
    kafkaMessages: Message[],
    overflowMode: IngestionOverflowMode
): IngestionSplitBatch {
    /**
     * Prepares micro-batches for use by eachBatchParallelIngestion:
     *   - events are parsed and grouped by token & distinct_id for sequential processing
     *   - if overflowMode=Reroute, messages to send to overflow are in the second array
     */
    const output: IngestionSplitBatch = {
        toProcess: [],
        toOverflow: [],
    }

    if (overflowMode === IngestionOverflowMode.ConsumeSplitEvenly) {
        /**
         * Grouping by distinct_id is inefficient here, because only a few ones are overflowing
         * at a time. When messages are sent to overflow, we already give away the ordering guarantee,
         * so we just return batches of one to increase concurrency.
         * TODO: add a PipelineEvent[] field to IngestionSplitBatch for batches of 1
         */
        for (const message of kafkaMessages) {
            // Drop based on a token blocklist
            const pluginEvent = formPipelineEvent(message)
            if (pluginEvent.token && tokenBlockList(pluginEvent.token)) {
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'blocked_token',
                    })
                    .inc()
                continue
            }
            output.toProcess.push(new Array({ message: message, pluginEvent }))
        }

        return output
    }

    const batches: Map<string, { message: Message; pluginEvent: PipelineEvent }[]> = new Map()
    for (const message of kafkaMessages) {
        if (overflowMode === IngestionOverflowMode.Reroute && message.key == null) {
            // Overflow detected by capture, reroute to overflow topic
            // Not applying tokenBlockList to save CPU. TODO: do so once token is in the message headers
            output.toOverflow.push(message)
            continue
        }
        const pluginEvent = formPipelineEvent(message)

        // Drop based on a token blocklist
        if (pluginEvent.token && tokenBlockList(pluginEvent.token)) {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'blocked_token',
                })
                .inc()
            continue
        }

        const eventKey = computeKey(pluginEvent)
        if (
            overflowMode === IngestionOverflowMode.Reroute &&
            !ConfiguredLimiter.consume(eventKey, 1, message.timestamp)
        ) {
            // Local overflow detection triggering, reroute to overflow topic too
            message.key = null
            ingestionPartitionKeyOverflowed.labels(`${pluginEvent.team_id ?? pluginEvent.token}`).inc()
            if (LoggingLimiter.consume(eventKey, 1)) {
                status.warn('🪣', `Local overflow detection triggered on key ${eventKey}`)
            }
            output.toOverflow.push(message)
            continue
        }
        const siblings = batches.get(eventKey)
        if (siblings) {
            siblings.push({ message, pluginEvent })
        } else {
            batches.set(eventKey, [{ message, pluginEvent }])
        }
    }
    output.toProcess = Array.from(batches.values())
    return output
}
