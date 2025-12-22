// Metrics that make sense across all Kafka consumers
import { Counter, Gauge, Histogram, Summary } from 'prom-client'

export const kafkaRebalancePartitionCount = new Gauge({
    name: 'kafka_rebalance_partition_count',
    help: 'Number of partitions assigned to this consumer. (Calculated during rebalance events.)',
    labelNames: ['topic'],
})

export const kafkaConsumerAssignment = new Gauge({
    name: 'kafka_consumer_assignment',
    help: 'Kafka consumer partition assignment status',
    labelNames: ['topic_name', 'partition_id', 'pod', 'group_id'],
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

export const setUsageInNonPersonEventsCounter = new Counter({
    name: 'set_usage_in_non_person_events',
    help: 'Count of events where $set usage was found in non-person events',
})

export const workflowE2eLagMsSummary = new Summary({
    name: 'workflow_e2e_lag_ms',
    help: 'Time difference in ms between event capture time and workflow finishing time',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const cookielessRedisErrorCounter = new Counter({
    name: 'cookieless_redis_error',
    help: 'Count redis errors.',
    labelNames: ['operation'],
})

export const kafkaHeaderStatusCounter = new Counter({
    name: 'kafka_header_status_total',
    help: 'Count of events by header name and presence status',
    labelNames: ['header', 'status'],
})

export const ingestionLagGauge = new Gauge({
    name: 'ingestion_lag_ms',
    help: 'Time difference in ms between event capture time (now header) and ingestion time',
    labelNames: ['topic', 'partition', 'groupId'],
})

export const ingestionLagHistogram = new Histogram({
    name: 'ingestion_lag_ms_histogram',
    help: 'Distribution of ingestion lag per event in ms',
    labelNames: ['groupId', 'partition'],
    buckets: [1000, 2000, 5000, 10000, 30000, 60000, 120000, 300000, 600000, 900000],
})
