// Metrics that make sense across all Kafka consumers

import { Counter, Gauge } from 'prom-client'

export const kafkaRebalancePartitionCount = new Gauge({
    name: 'kafka_rebalance_partition_count',
    help: 'Number of partitions assigned to this consumer. (Calculated during rebalance events.)',
    labelNames: ['topic'],
})

export const latestOffsetTimestampGauge = new Gauge({
    name: 'latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

export const eventDroppedCounter = new Counter({
    name: 'ingestion_event_dropped_total',
    help: 'Count of events dropped by the ingestion pipeline, by type and cause.',
    labelNames: ['event_type', 'drop_cause'],
})
