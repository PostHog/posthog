import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { CompressionCodecs, CompressionTypes, KafkaJSError, Message, Producer, ProducerRecord } from 'kafkajs'
// @ts-expect-error no type definitions
import SnappyCodec from 'kafkajs-snappy'

import { runInSpan } from '../../sentry'
import { PluginsServerConfig } from '../../types'
import { instrument } from '../metrics'
import { status } from '../status'
import { DependencyUnavailableError } from './error'
import { timeoutGuard } from './utils'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

/** This class wraps kafkajs producer, adding batching to optimize performance.
 *
 * As messages get queued, we flush the queue in the following cases.
 *
 * 1. Message size + current batch exceeds max batch message size
 * 2. Too much time passed
 * 3. Too many messages queued.
 *
 * We also flush the queue regularly to avoid dropping any messages as the program quits.
 */
export class KafkaProducerWrapper {
    /** StatsD instance used to do instrumentation */
    private statsd: StatsD | undefined

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    producer: Producer

    lastFlushTime: number
    currentBatch: Array<ProducerRecord>
    currentBatchSize: number

    flushFrequencyMs: number
    maxQueueSize: number
    maxBatchSize: number

    flushInterval: NodeJS.Timeout | undefined

    constructor(producer: Producer, statsd: StatsD | undefined, serverConfig: PluginsServerConfig) {
        this.producer = producer
        this.statsd = statsd

        this.lastFlushTime = Date.now()
        this.currentBatch = []
        this.currentBatchSize = 0

        this.flushFrequencyMs = serverConfig.KAFKA_FLUSH_FREQUENCY_MS
        this.maxQueueSize = serverConfig.KAFKA_PRODUCER_MAX_QUEUE_SIZE
        this.maxBatchSize = serverConfig.KAFKA_MAX_MESSAGE_BATCH_SIZE

        if (this.flushFrequencyMs > 0) {
            // If flush frequency is set, we flush the queue at intervals. We
            // allow disabling this to avoid out of band flushing occuring for
            // which we would not be able to explicitly handle.
            this.flushInterval = setInterval(async () => {
                // :TRICKY: Swallow uncaught errors from flush as flush is already doing custom error reporting which would get lost.
                try {
                    await this.flush()
                } catch (err) {}
            }, this.flushFrequencyMs)
        }
    }

    queueMessage(kafkaMessage: ProducerRecord): Promise<void> {
        return runInSpan(
            {
                op: 'kafka.queueMessage',
                description: kafkaMessage.topic,
            },
            async () => {
                const messageSize = this.estimateMessageSize(kafkaMessage)

                if (this.currentBatch.length > 0 && this.currentBatchSize + messageSize > this.maxBatchSize) {
                    // :TRICKY: We want to first flush then immediately add the message to the queue. Awaiting and then pushing would result in a race condition.
                    await this.flush(kafkaMessage)
                } else {
                    this.currentBatch.push(kafkaMessage)
                    this.currentBatchSize += messageSize

                    const timeSinceLastFlush = Date.now() - this.lastFlushTime
                    if (
                        this.currentBatchSize > this.maxBatchSize ||
                        timeSinceLastFlush > this.flushFrequencyMs ||
                        this.currentBatch.length >= this.maxQueueSize
                    ) {
                        await this.flush()
                    }
                }
            }
        )
    }

    async queueMessages(kafkaMessages: ProducerRecord[]): Promise<void> {
        for (const message of kafkaMessages) {
            await this.queueMessage(message)
        }
    }

    async queueSingleJsonMessage(topic: string, key: Message['key'], object: Record<string, any>): Promise<void> {
        await this.queueMessage({
            topic,
            messages: [{ key, value: JSON.stringify(object) }],
        })
    }

    public flush(append?: ProducerRecord): Promise<void> {
        if (this.currentBatch.length === 0) {
            return Promise.resolve()
        }

        return instrument(this.statsd, { metricName: 'query.kafka_send' }, async () => {
            const messages = this.currentBatch
            const batchSize = this.currentBatchSize
            this.lastFlushTime = Date.now()
            this.currentBatch = append ? [append] : []
            this.currentBatchSize = append ? this.estimateMessageSize(append) : 0

            this.statsd?.histogram('query.kafka_send.size', batchSize)
            const timeout = timeoutGuard('Kafka message sending delayed. Waiting over 30 sec to send messages.')

            try {
                await this.producer.sendBatch({
                    topicMessages: messages,
                    compression: CompressionTypes.Snappy,
                })
            } catch (err) {
                Sentry.captureException(err, {
                    extra: {
                        batchCount: messages.length,
                        topics: messages.map((record) => record.topic),
                        messageCounts: messages.map((record) => record.messages.length),
                        estimatedSize: batchSize,
                    },
                })
                // :TODO: Implement some retrying, https://github.com/PostHog/plugin-server/issues/511
                this.statsd?.increment('query.kafka_send.failure', {
                    firstTopic: messages[0].topic,
                })
                status.error('⚠️', 'Failed to flush kafka messages that were produced', {
                    error: err,
                    batchCount: messages.length,
                    topics: messages.map((record) => record.topic),
                    messageCounts: messages.map((record) => record.messages.length),
                    estimatedSize: batchSize,
                })

                if (err instanceof KafkaJSError) {
                    if (err.retriable === true) {
                        throw new DependencyUnavailableError(err.name, 'Kafka', err)
                    }
                }

                throw err
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    public async disconnect(): Promise<void> {
        clearInterval(this.flushInterval)
        await this.flush()
        await this.producer.disconnect()
    }

    private estimateMessageSize(kafkaMessage: ProducerRecord): number {
        // :TRICKY: This length respects unicode
        return Buffer.from(JSON.stringify(kafkaMessage)).length
    }
}
