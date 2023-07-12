import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../config/kafka-topics'
import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { normalizeEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { ConfiguredLimiter, LoggingLimiter, WarningLimiter } from '../../../utils/token-bucket'
import { EventPipelineResult } from '../../../worker/ingestion/event-pipeline/runner'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { ingestionPartitionKeyOverflowed } from '../analytics-events-ingestion-consumer'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'
import { IngestionOverflowMode } from './each-batch-ingestion'
import {
    ingestionOverflowingMessagesTotal,
    ingestionParallelism,
    ingestionParallelismPotential,
    kafkaBatchOffsetCommitted,
    kafkaBatchStart,
} from './metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

type IngestionSplitBatch = {
    toProcess: { message: KafkaMessage; pluginEvent: PipelineEvent }[][]
    toOverflow: KafkaMessage[]
}

// Subset of EventPipelineResult to make sure we don't access what's exported for the tests
type IngestResult = {
    // Promises that the batch handler should await on before committing offsets,
    // contains the Kafka producer ACKs, to avoid blocking after every message.
    promises?: Array<Promise<void>>
}

/**
 * Legacy consumer loop that uses the kafkajs consumer, kept as a fallback while we iterate on
 * eachBatchParallelIngestion and rdkafka.
 * TODO: delete as soon as rdkafka is tuned and ready for prime time.
 */
export async function eachBatchLegacyIngestion(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: KafkaJSIngestionConsumer,
    overflowMode: IngestionOverflowMode
): Promise<void> {
    async function eachMessage(event: PipelineEvent, queue: KafkaJSIngestionConsumer): Promise<IngestResult> {
        return ingestEvent(queue.pluginsServer, queue.workerMethods, event)
    }

    const batchStartTimer = new Date()
    const metricKey = 'ingestion'
    const loggingKey = `each_batch_legacy_ingestion`

    const transaction = Sentry.startTransaction({ name: `eachBatchLegacyIngestion` }, { topic: queue.topic })

    try {
        /**
         * Micro-batches should be executed from biggest to smallest to enable the best concurrency.
         * We're sorting with biggest last and pop()ing. Ideally, we'd use a priority queue by length
         * and a separate array for single messages, but let's look at profiles before optimizing.
         */
        const prepareSpan = transaction.startChild({ op: 'prepareBatch' })
        const splitBatch = splitKafkaJSIngestionBatch(batch.messages, overflowMode)
        splitBatch.toProcess.sort((a, b) => a.length - b.length)

        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, {
            key: metricKey,
        })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', splitBatch.toProcess.length, {
            key: metricKey,
        })
        prepareSpan.finish()

        const processingPromises: Array<Promise<void>> = []

        async function processMicroBatches(
            batches: { message: KafkaMessage; pluginEvent: PipelineEvent }[][]
        ): Promise<void> {
            let currentBatch
            let processedBatches = 0
            while ((currentBatch = batches.pop()) !== undefined) {
                const batchSpan = transaction.startChild({
                    op: 'messageBatch',
                    data: { batchLength: currentBatch.length },
                })

                // Process overflow ingestion warnings
                if (overflowMode == IngestionOverflowMode.Consume && currentBatch.length > 0) {
                    const team = await queue.pluginsServer.teamManager.getTeamForEvent(currentBatch[0].pluginEvent)
                    const distinct_id = currentBatch[0].pluginEvent.distinct_id
                    if (team && WarningLimiter.consume(`${team.id}:${distinct_id}`, 1)) {
                        await captureIngestionWarning(queue.pluginsServer.db, team.id, 'ingestion_capacity_overflow', {
                            overflowDistinctId: distinct_id,
                        })
                    }
                }

                // Process every message sequentially, stash promises to await on later
                for (const { message, pluginEvent } of currentBatch) {
                    try {
                        const result = await eachMessage(pluginEvent, queue)
                        if (result.promises) {
                            processingPromises.push(...result.promises)
                        }
                    } catch (error) {
                        status.error('🔥', `Error processing message`, {
                            stack: error.stack,
                            error: error,
                        })

                        // If there error is a non-retriable error, push
                        // to the dlq and commit the offset. Else raise the
                        // error.
                        //
                        // NOTE: there is behavior to push to a DLQ at the
                        // moment within EventPipelineRunner. This doesn't work
                        // so well with e.g. messages that when sent to the DLQ
                        // is it's self too large. Here we explicitly do _not_
                        // add any additional metadata to the message. We might
                        // want to add some metadata to the message e.g. in the
                        // header or reference e.g. the sentry event id.
                        //
                        // TODO: property abstract out this `isRetriable` error
                        // logic. This is currently relying on the fact that
                        // node-rdkafka adheres to the `isRetriable` interface.
                        if (error?.isRetriable === false) {
                            const sentryEventId = Sentry.captureException(error)
                            try {
                                await queue.pluginsServer.kafkaProducer.queueMessage({
                                    topic: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
                                    messages: [
                                        {
                                            ...message,
                                            headers: {
                                                ...message.headers,
                                                'sentry-event-id': sentryEventId,
                                                'event-id': pluginEvent.uuid,
                                            },
                                        },
                                    ],
                                })
                            } catch (error) {
                                // If we can't send to the DLQ and it's not
                                // retriable, just continue. We'll commit the
                                // offset and move on.
                                if (error?.isRetriable === false) {
                                    status.error('🔥', `Error pushing to DLQ`, {
                                        stack: error.stack,
                                        error: error,
                                    })
                                    continue
                                }

                                // If we can't send to the DLQ and it is
                                // retriable, raise the error.
                                throw error
                            }
                        } else {
                            throw error
                        }
                    }
                }

                // Emit the Kafka heartbeat if needed then close the micro-batch
                await heartbeat()
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
        await Promise.all(tasks)

        // Process overflow after the main batch is successful to reduce the risk of duplicates
        // generated by batch retries. Delay ACKs into processingPromises too.
        if (splitBatch.toOverflow.length > 0) {
            const overflowSpan = transaction.startChild({
                op: 'emitToOverflow',
                data: { eventCount: splitBatch.toOverflow.length },
            })
            processingPromises.push(emitToOverflow(queue, splitBatch.toOverflow))
            overflowSpan.finish()
        }

        // Await on successful Kafka writes before closing the batch. At this point, messages
        // have been successfully queued in the producer, only broker / network failures could
        // impact the success. Delaying ACKs allows the producer to write in big batches for
        // better throughput and lower broker load.
        const awaitSpan = transaction.startChild({ op: 'awaitACKs', data: { promiseCount: processingPromises.length } })
        await Promise.all(processingPromises)
        awaitSpan.finish()

        // Commit offsets once at the end of the batch. We run the risk of duplicates
        // if the pod is prematurely killed in the middle of a batch, but this allows
        // us to process events out of order within a batch, for higher throughput.
        const commitSpan = transaction.startChild({ op: 'offsetCommit' })
        const lastMessage = batch.messages.at(-1)
        if (lastMessage) {
            resolveOffset(lastMessage.offset)
            await commitOffsetsIfNecessary()
            latestOffsetTimestampGauge
                .labels({ partition: batch.partition, topic: batch.topic, groupId: metricKey })
                .set(Number.parseInt(lastMessage.timestamp))
        }
        commitSpan.finish()
        kafkaBatchOffsetCommitted.inc() // and we successfully committed the offsets

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

async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PipelineEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<EventPipelineResult> {
    const eachEventStartTimer = new Date()

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit', {
        pipeline: 'runEventPipeline',
    })
    const result = await workerMethods.runEventPipeline(event)

    server.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)
    countAndLogEvents()

    return result
}

let messageCounter = 0
let messageLogDate = 0

function computeKey(pluginEvent: PipelineEvent): string {
    return `${pluginEvent.team_id ?? pluginEvent.token}:${pluginEvent.distinct_id}`
}

async function emitToOverflow(queue: KafkaJSIngestionConsumer, kafkaMessages: KafkaMessage[]) {
    ingestionOverflowingMessagesTotal.inc(kafkaMessages.length)
    await Promise.all(
        kafkaMessages.map((message) =>
            queue.pluginsServer.kafkaProducer.queueMessage(
                {
                    topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                    messages: [message],
                },
                true
            )
        )
    )
}

export function splitKafkaJSIngestionBatch(
    kafkaMessages: KafkaMessage[],
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

    if (overflowMode === IngestionOverflowMode.Consume) {
        /**
         * Grouping by distinct_id is inefficient here, because only a few ones are overflowing
         * at a time. When messages are sent to overflow, we already give away the ordering guarantee,
         * so we just return batches of one to increase concurrency.
         * TODO: add a PipelineEvent[] field to IngestionSplitBatch for batches of 1
         */
        output.toProcess = kafkaMessages.map((m) => new Array({ message: m, pluginEvent: formPipelineEvent(m) }))
        return output
    }

    const batches: Map<string, { message: KafkaMessage; pluginEvent: PipelineEvent }[]> = new Map()
    for (const message of kafkaMessages) {
        if (overflowMode === IngestionOverflowMode.Reroute && message.key == null) {
            // Overflow detected by capture, reroute to overflow topic
            output.toOverflow.push(message)
            continue
        }
        const pluginEvent = formPipelineEvent(message)
        const eventKey = computeKey(pluginEvent)
        if (overflowMode === IngestionOverflowMode.Reroute && !ConfiguredLimiter.consume(eventKey, 1)) {
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

function countAndLogEvents(): void {
    const now = new Date().valueOf()
    messageCounter++
    if (now - messageLogDate > 10000) {
        status.info(
            '🕒',
            `Processed ${messageCounter} events${
                messageLogDate === 0 ? '' : ` in ${Math.round((now - messageLogDate) / 10) / 100}s`
            }`
        )
        messageCounter = 0
        messageLogDate = now
    }
}

function formPipelineEvent(message: KafkaMessage): PipelineEvent {
    // TODO: inefficient to do this twice?
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...JSON.parse(dataStr), ...rawEvent }
    const event: PipelineEvent = normalizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    return event
}
