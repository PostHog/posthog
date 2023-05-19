import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { Hub, PipelineEvent, WorkerMethods } from '../../../types'
import { formPipelineEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { IngestionConsumer } from '../kafka-queue'
import { latestOffsetTimestampGauge } from '../metrics'
import { eachBatch } from './each-batch'

export async function eachMessageIngestion(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    const event = formPipelineEvent(message)
    await ingestEvent(queue.pluginsServer, queue.workerMethods, event)
}

export async function eachBatchIngestion(payload: EachBatchPayload, queue: IngestionConsumer): Promise<void> {
    function groupIntoBatchesIngestion(kafkaMessages: KafkaMessage[], batchSize: number): KafkaMessage[][] {
        // Once we see a distinct ID we've already seen break up the batch
        const batches = []
        const seenIds: Set<string> = new Set()
        let currentBatch: KafkaMessage[] = []
        for (const message of kafkaMessages) {
            const pluginEvent = formPipelineEvent(message)
            const seenKey = `${pluginEvent.team_id}:${pluginEvent.distinct_id}`
            if (currentBatch.length === batchSize || seenIds.has(seenKey)) {
                seenIds.clear()
                batches.push(currentBatch)
                currentBatch = []
            }
            seenIds.add(seenKey)
            currentBatch.push(message)
        }
        if (currentBatch) {
            batches.push(currentBatch)
        }
        return batches
    }

    await eachBatch(payload, queue, eachMessageIngestion, groupIntoBatchesIngestion, 'ingestion')
}

export async function eachBatchParallelIngestion(
    { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload,
    queue: IngestionConsumer
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
        const messageBatches = groupByTeamDistinctId(batch.messages)
        messageBatches.sort((a, b) => a.length - b.length)

        queue.pluginsServer.statsd?.histogram('ingest_event_batching.input_length', batch.messages.length, {
            key: metricKey,
        })
        queue.pluginsServer.statsd?.histogram('ingest_event_batching.batch_count', messageBatches.length, {
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
                for (const message of currentBatch) {
                    await Promise.all([eachMessage(message, queue), heartbeat()])
                }
                processedBatches++
                batchSpan.finish()
            }
            status.debug('🧩', `Stopping worker after processing ${processedBatches} micro-batches`)
            return Promise.resolve()
        }

        await Promise.all(
            [...Array(queue.pluginsServer.INGESTION_CONCURRENCY)].map(() => processMicroBatches(messageBatches))
        )

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

export function groupByTeamDistinctId(kafkaMessages: KafkaMessage[]): PipelineEvent[][] {
    const batches: Map<string, PipelineEvent[]> = new Map()
    for (const message of kafkaMessages) {
        const pluginEvent = formPipelineEvent(message)
        const key = `${pluginEvent.team_id ?? pluginEvent.token}:${pluginEvent.distinct_id}`
        const siblings = batches.get(key)
        if (siblings) {
            siblings.push(pluginEvent)
        } else {
            batches.set(key, [pluginEvent])
        }
    }

    return Array.from(batches.values())
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
