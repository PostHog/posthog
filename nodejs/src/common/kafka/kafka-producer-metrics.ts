import { Gauge } from 'prom-client'

import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { BrokerStats, LatencyWindowMicroseconds, producerStatsSchema } from './kafka-producer-stats-schema'

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

export const kafkaProducerBrokers = new Gauge({
    name: 'kafka_producer_brokers',
    help: 'Number of brokers the producer knows about, by librdkafka connection state (INIT, DOWN, UP, ...). Bootstrap entries are excluded.',
    labelNames: ['producer_name', 'state'],
})

export const kafkaProducerRequestsInFlight = new Gauge({
    name: 'kafka_producer_requests_in_flight',
    help: 'Requests sent to brokers that still wait for a response, summed over brokers.',
    labelNames: ['producer_name'],
})

export const kafkaProducerRequestsQueued = new Gauge({
    name: 'kafka_producer_requests_queued',
    help: 'Requests in broker output buffers that librdkafka has not sent yet, summed over brokers.',
    labelNames: ['producer_name'],
})

export const kafkaProducerBusiestBrokerRequestsInFlight = new Gauge({
    name: 'kafka_producer_busiest_broker_requests_in_flight',
    help: 'Requests in flight on the broker connection that has the most. Compare with max.in.flight.requests.per.connection.',
    labelNames: ['producer_name'],
})

export const kafkaProducerBrokerLatencySeconds = new Gauge({
    name: 'kafka_producer_broker_latency_seconds',
    help: 'librdkafka broker latency over the last stats window. stat=mean is over all brokers; stat=max_p99 is the highest broker p99. latency=internal_queue is the partition queue wait, request_queue is the output buffer wait, round_trip is the broker RTT.',
    labelNames: ['producer_name', 'latency', 'stat'],
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
    /** States reported at least once, so a state no broker is in any more is reset to zero rather than left stale. */
    private reportedBrokerStates = new Set<string>()

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
            const countsByState = new Map<string, number>()
            const learnedBrokers: BrokerStats[] = []
            for (const broker of Object.values(stats.brokers)) {
                // librdkafka lists configured bootstrap servers with nodeid -1 next to the learned brokers.
                const isBootstrap = broker.nodeid !== undefined && broker.nodeid < 0
                if (isBootstrap) {
                    continue
                }
                learnedBrokers.push(broker)
                if (broker.state !== undefined) {
                    countsByState.set(broker.state, (countsByState.get(broker.state) ?? 0) + 1)
                }
            }
            this.trackBrokerRequests(learnedBrokers)
            for (const state of this.reportedBrokerStates) {
                if (!countsByState.has(state)) {
                    kafkaProducerBrokers.set({ ...labels, state }, 0)
                }
            }
            for (const [state, count] of countsByState) {
                kafkaProducerBrokers.set({ ...labels, state }, count)
                this.reportedBrokerStates.add(state)
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

    private trackBrokerRequests(brokers: BrokerStats[]): void {
        const labels = { producer_name: this.producerName }
        const inFlightPerBroker = brokers.map((broker) => broker.waitresp_cnt ?? 0)
        kafkaProducerRequestsInFlight.set(
            labels,
            inFlightPerBroker.reduce((sum, count) => sum + count, 0)
        )
        kafkaProducerBusiestBrokerRequestsInFlight.set(labels, Math.max(0, ...inFlightPerBroker))
        kafkaProducerRequestsQueued.set(
            labels,
            brokers.reduce((sum, broker) => sum + (broker.outbuf_cnt ?? 0), 0)
        )
        this.trackBrokerLatency(
            'internal_queue',
            brokers.map((broker) => broker.int_latency)
        )
        this.trackBrokerLatency(
            'request_queue',
            brokers.map((broker) => broker.outbuf_latency)
        )
        this.trackBrokerLatency(
            'round_trip',
            brokers.map((broker) => broker.rtt)
        )
    }

    private trackBrokerLatency(
        latency: 'internal_queue' | 'request_queue' | 'round_trip',
        windows: (LatencyWindowMicroseconds | undefined)[]
    ): void {
        let sumMicroseconds = 0
        let sampleCount = 0
        let maxP99Microseconds = 0
        for (const window of windows) {
            if (!window?.cnt) {
                continue
            }
            sumMicroseconds += window.sum ?? 0
            sampleCount += window.cnt
            maxP99Microseconds = Math.max(maxP99Microseconds, window.p99 ?? 0)
        }
        const labels = { producer_name: this.producerName, latency }
        kafkaProducerBrokerLatencySeconds.set(
            { ...labels, stat: 'mean' },
            sampleCount > 0 ? sumMicroseconds / sampleCount / 1e6 : 0
        )
        kafkaProducerBrokerLatencySeconds.set({ ...labels, stat: 'max_p99' }, maxP99Microseconds / 1e6)
    }
}
