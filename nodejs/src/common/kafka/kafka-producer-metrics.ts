import { Gauge } from 'prom-client'

import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { producerStatsSchema } from './kafka-producer-stats-schema'

export const kafkaProducerQueueMessages = new Gauge({
    name: 'kafka_producer_queue_messages',
    help: 'Current number of messages in the producer queue.',
    labelNames: ['producer_name'],
})

export const kafkaProducerQueueBytes = new Gauge({
    name: 'kafka_producer_queue_bytes',
    help: 'Current size in bytes of messages in the producer queue.',
    labelNames: ['producer_name'],
})

export const kafkaProducerQueueMaxMessages = new Gauge({
    name: 'kafka_producer_queue_max_messages',
    help: 'Maximum number of messages allowed in the producer queue.',
    labelNames: ['producer_name'],
})

export const kafkaProducerQueueMaxBytes = new Gauge({
    name: 'kafka_producer_queue_max_bytes',
    help: 'Maximum size in bytes allowed in the producer queue.',
    labelNames: ['producer_name'],
})

export const kafkaProducerCallbackQueueDepth = new Gauge({
    name: 'kafka_producer_callback_queue_depth',
    help: 'Number of delivery-report callbacks queued for the main thread to process.',
    labelNames: ['producer_name'],
})

export const kafkaProducerAnyBrokersDown = new Gauge({
    name: 'kafka_producer_any_brokers_down',
    help: '1 if any broker the producer knows about is not in the UP state, 0 otherwise.',
    labelNames: ['producer_name'],
})

export const kafkaProducerTopicBatchSizeBytesAvg = new Gauge({
    name: 'kafka_producer_topic_batch_size_bytes_avg',
    help: 'Average Kafka produce batch size in bytes, per topic, over the rolling librdkafka window.',
    labelNames: ['producer_name', 'topic'],
})

export const kafkaProducerTopicBatchCountAvg = new Gauge({
    name: 'kafka_producer_topic_batch_count_avg',
    help: 'Average number of messages per produce batch, per topic, over the rolling librdkafka window.',
    labelNames: ['producer_name', 'topic'],
})

/**
 * Translates the librdkafka stats JSON emitted by the producer into Prometheus series.
 *
 * Deliberately does NOT fan out per-broker series: the {producer_name, broker} cross
 * product would explode cardinality. Broker-level observability is available via the
 * Kafka broker's own metrics — here we keep only client-level rollups.
 */
export class ProducerStatsTracker {
    private producerName: string

    constructor(producerName: string) {
        this.producerName = producerName
    }

    track(statsJson: string): void {
        let raw: unknown
        try {
            raw = parseJSON(statsJson)
        } catch (error) {
            logger.warn('📊', 'Failed to parse producer statistics JSON', {
                producer_name: this.producerName,
                error: error instanceof Error ? error.message : String(error),
            })
            return
        }

        const result = producerStatsSchema.safeParse(raw)
        if (!result.success) {
            logger.warn('📊', 'Producer statistics did not match expected schema', {
                producer_name: this.producerName,
                issues: result.error.issues,
            })
            return
        }
        const stats = result.data

        const labels = { producer_name: this.producerName }

        if (stats.msg_cnt !== undefined) {
            kafkaProducerQueueMessages.set(labels, stats.msg_cnt)
        }
        if (stats.msg_size !== undefined) {
            kafkaProducerQueueBytes.set(labels, stats.msg_size)
        }
        if (stats.msg_max !== undefined) {
            kafkaProducerQueueMaxMessages.set(labels, stats.msg_max)
        }
        if (stats.msg_size_max !== undefined) {
            kafkaProducerQueueMaxBytes.set(labels, stats.msg_size_max)
        }
        if (stats.replyq !== undefined) {
            kafkaProducerCallbackQueueDepth.set(labels, stats.replyq)
        }

        if (stats.brokers) {
            const brokers = Object.values(stats.brokers)
            if (brokers.length > 0) {
                const anyDown = brokers.some((b) => b.state !== 'UP')
                kafkaProducerAnyBrokersDown.set(labels, anyDown ? 1 : 0)
            }
        }

        if (stats.topics) {
            for (const [topic, topicStats] of Object.entries(stats.topics)) {
                const topicLabels = { producer_name: this.producerName, topic }
                if (topicStats.batchsize?.avg !== undefined) {
                    kafkaProducerTopicBatchSizeBytesAvg.set(topicLabels, topicStats.batchsize.avg)
                }
                if (topicStats.batchcnt?.avg !== undefined) {
                    kafkaProducerTopicBatchCountAvg.set(topicLabels, topicStats.batchcnt.avg)
                }
            }
        }
    }
}
