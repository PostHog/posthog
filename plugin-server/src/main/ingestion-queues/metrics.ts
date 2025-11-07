// Metrics that make sense across all Kafka consumers
import { Counter, Gauge, Summary } from 'prom-client'

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

export const kafkaConsumerEventCounter = new Counter({
    name: 'kafka_consumer_event_total',
    help: 'Count of events emitted by the Kafka consumer by event type',
    labelNames: ['event'],
})

export const kafkaConsumerEventRequestMsSummary = new Summary({
    name: 'kafka_consumer_event_request_ms',
    help: 'Duration of Kafka consumer event requests',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const kafkaConsumerEventRequestPendingMsSummary = new Summary({
    name: 'kafka_consumer_event_request_pending_ms',
    help: 'Pending duration of Kafka consumer event requests',
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
