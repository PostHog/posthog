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

export const kafkaProducerBrokerOutbufMessages = new Gauge({
    name: 'kafka_producer_broker_outbuf_messages',
    help: 'Messages awaiting transmission to the broker.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerInflightRequests = new Gauge({
    name: 'kafka_producer_broker_inflight_requests',
    help: 'Requests sent to broker awaiting response.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerRttP99Microseconds = new Gauge({
    name: 'kafka_producer_broker_rtt_p99_microseconds',
    help: 'Broker round-trip time p99 over the rolling librdkafka window, in microseconds.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerThrottleP99Milliseconds = new Gauge({
    name: 'kafka_producer_broker_throttle_p99_milliseconds',
    help: 'Broker throttle duration p99 over the rolling librdkafka window, in milliseconds.',
    labelNames: ['producer_name', 'broker'],
})

export const kafkaProducerBrokerTxErrorsTotal = new Counter({
    name: 'kafka_producer_broker_tx_errors_total',
    help: 'Broker transmit errors reported by librdkafka.',
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

type CumulativeBrokerStats = {
    txerrs: number
    txretries: number
    req_timeouts: number
    disconnects: number
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

        for (const [brokerName, broker] of parseBrokerStatistics(parsed)) {
            this.trackBroker(brokerName, broker)
        }
    }

    private trackBroker(brokerName: string, broker: BrokerStats): void {
        const labels = { producer_name: this.producerName, broker: brokerName }

        kafkaProducerBrokerOutbufMessages.set(labels, broker.outbuf_msg_cnt ?? 0)
        kafkaProducerBrokerInflightRequests.set(labels, broker.waitresp_cnt ?? 0)
        if (broker.rtt?.p99) {
            kafkaProducerBrokerRttP99Microseconds.set(labels, broker.rtt.p99)
        }
        if (broker.throttle?.p99) {
            kafkaProducerBrokerThrottleP99Milliseconds.set(labels, broker.throttle.p99)
        }

        const current: CumulativeBrokerStats = {
            txerrs: broker.txerrs ?? 0,
            txretries: broker.txretries ?? 0,
            req_timeouts: broker.req_timeouts ?? 0,
            disconnects: broker.disconnects ?? 0,
        }

        // Skip the first observation per broker — otherwise we'd jump the Prom counter by
        // whatever librdkafka accumulated before our first tick (usually zero, but not always).
        const last = this.lastBrokerCounters.get(brokerName)
        if (last) {
            incIfIncreased(kafkaProducerBrokerTxErrorsTotal, labels, current.txerrs, last.txerrs)
            incIfIncreased(kafkaProducerBrokerTxRetriesTotal, labels, current.txretries, last.txretries)
            incIfIncreased(kafkaProducerBrokerRequestTimeoutsTotal, labels, current.req_timeouts, last.req_timeouts)
            incIfIncreased(kafkaProducerBrokerDisconnectsTotal, labels, current.disconnects, last.disconnects)
        }
        this.lastBrokerCounters.set(brokerName, current)
    }
}

function incIfIncreased(counter: Counter<string>, labels: Record<string, string>, current: number, last: number): void {
    if (current > last) {
        counter.inc(labels, current - last)
    }
}
