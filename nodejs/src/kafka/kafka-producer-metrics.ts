import { Counter, Gauge } from 'prom-client'

import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { BrokerStats, parseBrokerStatistics } from './kafka-client-metrics'

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
    help: '1 if any broker is not in the UP state, 0 otherwise.',
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

export const kafkaProducerBrokerConnected = new Gauge({
    name: 'kafka_producer_broker_connected',
    help: '1 if the broker is in the UP state, 0 otherwise.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerOutbufMessages = new Gauge({
    name: 'kafka_producer_broker_outbuf_messages',
    help: 'Messages awaiting transmission to the broker.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerOutbufRequests = new Gauge({
    name: 'kafka_producer_broker_outbuf_requests',
    help: 'Protocol requests awaiting transmission to the broker.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerInflightRequests = new Gauge({
    name: 'kafka_producer_broker_inflight_requests',
    help: 'Requests sent to broker awaiting response.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerRttMicroseconds = new Gauge({
    name: 'kafka_producer_broker_rtt_microseconds',
    help: 'Broker round-trip time in microseconds, over the rolling librdkafka window. Labelled by quantile.',
    labelNames: ['producer_name', 'broker', 'quantile'],
})

export const kafkaProducerBrokerThrottleMilliseconds = new Gauge({
    name: 'kafka_producer_broker_throttle_milliseconds',
    help: 'Broker throttle duration in milliseconds, over the rolling librdkafka window. Labelled by quantile.',
    labelNames: ['producer_name', 'broker', 'quantile'],
})

export const kafkaProducerBrokerTxErrorsTotal = new Counter({
    name: 'kafka_producer_broker_tx_errors_total',
    help: 'Broker transmit errors reported by librdkafka.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerRxErrorsTotal = new Counter({
    name: 'kafka_producer_broker_rx_errors_total',
    help: 'Broker receive errors reported by librdkafka.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerTxRetriesTotal = new Counter({
    name: 'kafka_producer_broker_tx_retries_total',
    help: 'Broker transmit retries reported by librdkafka.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerRequestTimeoutsTotal = new Counter({
    name: 'kafka_producer_broker_request_timeouts_total',
    help: 'Broker request timeouts reported by librdkafka.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerDisconnectsTotal = new Counter({
    name: 'kafka_producer_broker_disconnects_total',
    help: 'Broker disconnects reported by librdkafka.',
    labelNames: ['producer_name', 'broker'],
})

const RTT_QUANTILES = ['p50', 'p90', 'p95', 'p99'] as const

type CumulativeBrokerStats = {
    txerrs: number
    txretries: number
    req_timeouts: number
    disconnects: number
    rxerrs: number
}

type TopicStats = {
    batchsize?: { avg?: number }
    batchcnt?: { avg?: number }
}

/**
 * Tracks per-broker cumulative counter deltas so we can expose librdkafka's
 * monotonic counters as Prometheus counters. Stateful per producer instance.
 */
export class ProducerStatsTracker {
    private producerName: string
    private lastBrokerCounters = new Map<string, CumulativeBrokerStats>()

    constructor(producerName: string) {
        this.producerName = producerName
    }

    track(statsJson: string): void {
        let parsed: any
        try {
            parsed = parseJSON(statsJson)
        } catch (error) {
            logger.error('📊', 'Failed to parse producer statistics', {
                producer_name: this.producerName,
                error: error instanceof Error ? error.message : String(error),
            })
            return
        }

        const labels = { producer_name: this.producerName }

        if (typeof parsed.msg_cnt === 'number') {
            kafkaProducerQueueMessages.set(labels, parsed.msg_cnt)
        }
        if (typeof parsed.msg_size === 'number') {
            kafkaProducerQueueBytes.set(labels, parsed.msg_size)
        }
        if (typeof parsed.msg_max === 'number') {
            kafkaProducerQueueMaxMessages.set(labels, parsed.msg_max)
        }
        if (typeof parsed.msg_size_max === 'number') {
            kafkaProducerQueueMaxBytes.set(labels, parsed.msg_size_max)
        }
        if (typeof parsed.replyq === 'number') {
            kafkaProducerCallbackQueueDepth.set(labels, parsed.replyq)
        }

        const brokers = parseBrokerStatistics(parsed)
        if (brokers.size > 0) {
            const anyDown = [...brokers.values()].some((b) => b.state !== 'UP')
            kafkaProducerAnyBrokersDown.set(labels, anyDown ? 1 : 0)
        }

        for (const [brokerName, broker] of brokers) {
            this.trackBroker(brokerName, broker)
        }

        if (parsed.topics && typeof parsed.topics === 'object') {
            for (const [topic, topicStats] of Object.entries(parsed.topics as Record<string, TopicStats>)) {
                this.trackTopic(topic, topicStats)
            }
        }
    }

    private trackBroker(brokerName: string, broker: BrokerStats): void {
        const labels = { producer_name: this.producerName, broker: brokerName }

        kafkaProducerBrokerConnected.set(labels, broker.state === 'UP' ? 1 : 0)
        kafkaProducerBrokerOutbufMessages.set(labels, broker.outbuf_msg_cnt ?? 0)
        kafkaProducerBrokerOutbufRequests.set(labels, broker.outbuf_cnt ?? 0)
        kafkaProducerBrokerInflightRequests.set(labels, broker.waitresp_cnt ?? 0)
        if (broker.rtt) {
            for (const q of RTT_QUANTILES) {
                const value = broker.rtt[q]
                if (typeof value === 'number') {
                    kafkaProducerBrokerRttMicroseconds.set({ ...labels, quantile: q }, value)
                }
            }
        }
        if (broker.throttle) {
            for (const q of RTT_QUANTILES) {
                const value = broker.throttle[q]
                if (typeof value === 'number') {
                    kafkaProducerBrokerThrottleMilliseconds.set({ ...labels, quantile: q }, value)
                }
            }
        }

        const current: CumulativeBrokerStats = {
            txerrs: broker.txerrs ?? 0,
            txretries: broker.txretries ?? 0,
            req_timeouts: broker.req_timeouts ?? 0,
            disconnects: broker.disconnects ?? 0,
            rxerrs: broker.rxerrs ?? 0,
        }

        // Skip the first observation per broker — otherwise we'd jump the Prom counter by
        // whatever librdkafka accumulated before our first tick (usually zero, but not always).
        const last = this.lastBrokerCounters.get(brokerName)
        if (last) {
            incIfIncreased(kafkaProducerBrokerTxErrorsTotal, labels, current.txerrs, last.txerrs)
            incIfIncreased(kafkaProducerBrokerRxErrorsTotal, labels, current.rxerrs, last.rxerrs)
            incIfIncreased(kafkaProducerBrokerTxRetriesTotal, labels, current.txretries, last.txretries)
            incIfIncreased(kafkaProducerBrokerRequestTimeoutsTotal, labels, current.req_timeouts, last.req_timeouts)
            incIfIncreased(kafkaProducerBrokerDisconnectsTotal, labels, current.disconnects, last.disconnects)
        }
        this.lastBrokerCounters.set(brokerName, current)
    }

    private trackTopic(topic: string, stats: TopicStats): void {
        const labels = { producer_name: this.producerName, topic }
        if (typeof stats.batchsize?.avg === 'number') {
            kafkaProducerTopicBatchSizeBytesAvg.set(labels, stats.batchsize.avg)
        }
        if (typeof stats.batchcnt?.avg === 'number') {
            kafkaProducerTopicBatchCountAvg.set(labels, stats.batchcnt.avg)
        }
    }
}

function incIfIncreased(counter: Counter<string>, labels: Record<string, string>, current: number, last: number): void {
    if (current > last) {
        counter.inc(labels, current - last)
    }
}
