import * as Sentry from '@sentry/node'
import { Message } from 'node-rdkafka-acosom'
import { exponentialBuckets, Histogram } from 'prom-client'

import { KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../config/kafka-topics'
import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { ConfiguredLimiter, LoggingLimiter, WarningLimiter } from '../../../utils/token-bucket'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { ingestionPartitionKeyOverflowed } from '../analytics-events-ingestion-consumer'
import { IngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export enum IngestionOverflowMode {
    Disabled,
    Reroute,
    Consume,
}

type IngestionSplitBatch = {
    toProcess: PipelineEvent[][]
    toOverflow: Message[]
}

export async function eachBatchParallelIngestion(
    messages: Message[],
    queue: IngestionConsumer,
    overflowMode: IngestionOverflowMode
): Promise<void> {
    async function eachMessage(event: PipelineEvent, queue: IngestionConsumer): Promise<void> {
        await ingestEvent(queue.pluginsServer, queue.workerMethods, event)
    }

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
        const splitBatch = splitIngestionBatch(messages, overflowMode)
        splitBatch.toProcess.sort((a, b) => a.length - b.length)

        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', messages.length, {
            key: metricKey,
        })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', splitBatch.toProcess.length, {
            key: metricKey,
        })

        async function processMicroBatches(batches: PipelineEvent[][]): Promise<void> {
            let currentBatch
            let processedBatches = 0
            while ((currentBatch = batches.pop()) !== undefined) {
                const batchSpan = transaction.startChild({
                    op: 'messageBatch',
                    data: { batchLength: currentBatch.length },
                })

                if (overflowMode == IngestionOverflowMode.Consume && currentBatch.length > 0) {
                    const team = await queue.pluginsServer.teamManager.getTeamForEvent(currentBatch[0])
                    const distinct_id = currentBatch[0].distinct_id
                    if (team && WarningLimiter.consume(`${team.id}:${distinct_id}`, 1)) {
                        captureIngestionWarning(queue.pluginsServer.db, team.id, 'ingestion_capacity_overflow', {
                            overflowDistinctId: distinct_id,
                        })
                    }
                }

                for (const message of currentBatch) {
                    await eachMessage(message, queue)
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
        const tasks = [...Array(parallelism)].map(() => processMicroBatches(splitBatch.toProcess))
        if (splitBatch.toOverflow.length > 0) {
            tasks.push(emitToOverflow(queue, splitBatch.toOverflow))
        }
        await Promise.all(tasks)

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: metricKey })
                    .set(message.timestamp)
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
        transaction.finish()
    }
}

export async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PipelineEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<void> {
    const eachEventStartTimer = new Date()

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit', {
        pipeline: 'runEventPipeline',
    })
    await workerMethods.runEventPipeline(event)

    server.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)

    countAndLogEvents()
}

let messageCounter = 0
let messageLogDate = 0

function computeKey(pluginEvent: PipelineEvent): string {
    return `${pluginEvent.team_id ?? pluginEvent.token}:${pluginEvent.distinct_id}`
}

async function emitToOverflow(queue: IngestionConsumer, kafkaMessages: Message[]) {
    await Promise.all(
        kafkaMessages.map((message) =>
            queue.pluginsServer.kafkaProducer.produce({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                value: message.value,
                key: message.key,
                headers: message.headers,
                waitForAck: true,
            })
        )
    )
}

export function splitIngestionBatch(
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

    if (overflowMode === IngestionOverflowMode.Consume) {
        /**
         * Grouping by distinct_id is inefficient here, because only a few ones are overflowing
         * at a time. When messages are sent to overflow, we already give away the ordering guarantee,
         * so we just return batches of one to increase concurrency.
         * TODO: add a PipelineEvent[] field to IngestionSplitBatch for batches of 1
         */
        output.toProcess = kafkaMessages.map((m) => new Array(formPipelineEvent(m)))
        return output
    }

    const batches: Map<string, PipelineEvent[]> = new Map()
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
            siblings.push(pluginEvent)
        } else {
            batches.set(eventKey, [pluginEvent])
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

const ingestionParallelism = new Histogram({
    name: 'ingestion_batch_parallelism',
    help: 'Processing parallelism per ingestion consumer batch',
    labelNames: ['overflow_mode'],
    buckets: exponentialBuckets(1, 2, 7), // Up to 64
})

const ingestionParallelismPotential = new Histogram({
    name: 'ingestion_batch_parallelism_potential',
    help: 'Number of eligible parts per ingestion consumer batch',
    labelNames: ['overflow_mode'],
    buckets: exponentialBuckets(1, 2, 7), // Up to 64
})
