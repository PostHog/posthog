import { Counter, Histogram } from 'prom-client'

import { logger } from '../utils/logger'

// Thresholds for broker state monitoring (in microseconds)
const SSL_HANDSHAKE_TIMEOUT_THRESHOLD_US = 5_000_000
const AUTH_TIMEOUT_THRESHOLD_US = 10_000_000

export const kafkaBrokerRtt = new Histogram({
    name: 'kafka_broker_rtt_ms',
    help: 'Round trip time to broker in milliseconds',
    labelNames: ['broker_id', 'broker_name', 'consumer_group'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

export const kafkaBrokerSslHandshakeFailures = new Counter({
    name: 'kafka_broker_ssl_handshake_failures_total',
    help: 'Total number of SSL handshake failures',
    labelNames: ['broker_id', 'broker_name', 'consumer_group', 'error'],
})

export const kafkaBrokerAuthFailures = new Counter({
    name: 'kafka_broker_auth_failures_total',
    help: 'Total number of authentication failures',
    labelNames: ['broker_id', 'broker_name', 'consumer_group'],
})

export const kafkaPartitionFetchErrors = new Counter({
    name: 'kafka_partition_fetch_errors_total',
    help: 'Total number of partition fetch errors',
    labelNames: ['broker_id', 'topic', 'partition', 'fetch_state', 'consumer_group'],
})

// interfaces pulled from here:
// https://docs.confluent.io/platform/current/clients/librdkafka/html/md_STATISTICS.html
export interface PartitionData {
    topic: string
    partition: number
    leader: number
    desired: boolean
    unknown: boolean
    msgq_cnt: number
    msgq_bytes: number
    xmit_msgq_cnt: number
    xmit_msgq_bytes: number
    fetchq_cnt: number
    fetchq_size: number
    fetch_state: string
    query_offset: number
    next_offset: number
    app_offset: number
    stored_offset: number
    committed_offset: number
    eof_offset: number
    lo_offset: number
    hi_offset: number
    ls_offset: number
    consumer_lag: number
    consumer_lag_stored: number
    txmsgs: number
    txbytes: number
    rxmsgs: number
    rxbytes: number
    msgs: number
    rx_ver_drops: number
    msgs_inflight: number
    next_ack_seq: number
    next_err_seq: number
    acked_msgid: number
}

export interface BrokerStats {
    name: string
    nodeid: number
    nodename: string
    source: string
    state: string
    // time since last broker state change (in microseconds)
    stateage: number
    outbuf_cnt: number
    outbuf_msg_cnt: number
    waitresp_cnt: number
    waitresp_msg_cnt: number
    tx: number
    txbytes: number
    txerrs: number
    txretries: number
    txidle: number
    req_timeouts: number
    rx: number
    rxbytes: number
    rxerrs: number
    rxcorriderrs: number
    rxpartial: number
    rxidle: number
    zbuf_grow: number
    buf_grow: number
    wakeups: number
    // number of connections attempts, including successful and failed, and name resolution failures
    connects: number
    // number of disconnects (triggered by broker, network, load-balancer, etc)
    disconnects: number
    int_latency: {
        min: number
        max: number
        avg: number
        sum: number
        stddev: number
        p50: number
        p75: number
        p90: number
        p95: number
        p99: number
        p99_99: number
        outofrange: number
        hdrsize: number
        cnt: number
    }
    outbuf_latency: {
        min: number
        max: number
        avg: number
        sum: number
        stddev: number
        p50: number
        p75: number
        p90: number
        p95: number
        p99: number
        p99_99: number
        outofrange: number
        hdrsize: number
        cnt: number
    }
    rtt: {
        min: number
        max: number
        avg: number
        sum: number
        stddev: number
        p50: number
        p75: number
        p90: number
        p95: number
        p99: number
        p99_99: number
        outofrange: number
        hdrsize: number
        cnt: number
    }
    throttle: {
        min: number
        max: number
        avg: number
        sum: number
        stddev: number
        p50: number
        p75: number
        p90: number
        p95: number
        p99: number
        p99_99: number
        outofrange: number
        hdrsize: number
        cnt: number
    }
    toppars?: {
        [topicPartition: string]: {
            topic: string
            partition: number
        }
    }
}

export function parseBrokerStatistics(stats: any): Map<string, BrokerStats> {
    const brokerStats = new Map<string, BrokerStats>()

    if (!stats.brokers) {
        return brokerStats
    }

    for (const [brokerName, broker] of Object.entries(stats.brokers)) {
        if (typeof broker === 'object' && broker !== null) {
            brokerStats.set(brokerName, broker as BrokerStats)
        }
    }
    return brokerStats
}

export function parsePartitionStatistics(
    stats: any
): Array<{ topicName: string; partitionId: string; partitionData: PartitionData }> {
    const partitionStats: Array<{ topicName: string; partitionId: string; partitionData: PartitionData }> = []

    if (!stats.topics) {
        return partitionStats
    }

    for (const [topicName, topic] of Object.entries(stats.topics)) {
        if (typeof topic === 'object' && topic !== null) {
            const topicData = topic as any
            if (topicData.partitions) {
                for (const [partitionId, partition] of Object.entries(topicData.partitions)) {
                    if (typeof partition === 'object' && partition !== null) {
                        partitionStats.push({
                            topicName,
                            partitionId,
                            partitionData: partition as PartitionData,
                        })
                    }
                }
            }
        }
    }

    return partitionStats
}

export function trackBrokerMetrics(
    brokerStats: Map<string, BrokerStats>,
    consumerGroup: string,
    consumerId: string
): void {
    for (const [brokerName, stats] of brokerStats) {
        const labels = {
            broker_id: String(stats.nodeid),
            broker_name: brokerName,
            consumer_group: consumerGroup,
        }

        if (stats.rtt?.avg) {
            kafkaBrokerRtt.observe(labels, stats.rtt.avg)
        }

        // Check for broker connection issues
        if (stats.state === 'DOWN' || stats.state === 'CONNECT') {
            logger.error('Broker connection issue', {
                ...labels,
                consumer_id: consumerId,
                state: stats.state,
                stateage: stats.stateage,
                connects: stats.connects,
                disconnects: stats.disconnects,
                txerrs: stats.txerrs,
                rxerrs: stats.rxerrs,
            })
        }

        // ssl handshake issues
        if (stats.state === 'SSL_HANDSHAKE' && stats.stateage > SSL_HANDSHAKE_TIMEOUT_THRESHOLD_US) {
            kafkaBrokerSslHandshakeFailures.inc({
                ...labels,
                error: 'ssl_handshake_timeout',
            })
            logger.error('SSL handshake stuck', {
                ...labels,
                consumer_id: consumerId,
                stateage_ms: stats.stateage,
            })
        }

        // auth issues
        if ((stats.state === 'AUTH' || stats.state === 'SASL_AUTH') && stats.stateage > AUTH_TIMEOUT_THRESHOLD_US) {
            kafkaBrokerAuthFailures.inc({
                ...labels,
            })
            logger.error('Authentication stuck', {
                ...labels,
                consumer_id: consumerId,
                stateage_ms: stats.stateage,
            })
        }

        // communication errors
        if (stats.txerrs > 0 || stats.rxerrs > 0) {
            logger.warn('Broker communication errors', {
                ...labels,
                consumer_id: consumerId,
                txerrs: stats.txerrs,
                rxerrs: stats.rxerrs,
                txretries: stats.txretries,
                req_timeouts: stats.req_timeouts,
            })
        }

        // request timeouts
        if (stats.req_timeouts > 0) {
            logger.warn('Broker request timeouts', {
                ...labels,
                consumer_id: consumerId,
                req_timeouts: stats.req_timeouts,
                waitresp_cnt: stats.waitresp_cnt,
                waitresp_msg_cnt: stats.waitresp_msg_cnt,
            })
        }
    }
}

export function trackPartitionMetrics(
    topicName: string,
    partitionId: string,
    partitionData: PartitionData,
    consumerGroup: string,
    consumerId: string
): void {
    const labels = {
        topic: topicName,
        partition: partitionId,
        leader_broker: String(partitionData.leader || 'unknown'),
        consumer_group: consumerGroup,
    }

    if (partitionData.fetch_state === 'stopped' || partitionData.fetch_state === 'stopping') {
        kafkaPartitionFetchErrors.inc({
            ...labels,
            broker_id: String(partitionData.leader),
            fetch_state: String(partitionData.fetch_state || 'unknown'),
        })

        logger.warn('Partition fetching stopped or stopping...', {
            ...labels,
            consumer_id: consumerId,
            fetch_state: partitionData.fetch_state,
            consumer_lag: partitionData.consumer_lag,
            leader_broker: partitionData.leader,
            msgq_cnt: partitionData.msgq_cnt,
            fetchq_cnt: partitionData.fetchq_cnt,
        })
    }
}
