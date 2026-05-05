import { Counter, Gauge, Histogram } from 'prom-client'

/**
 * Prom-client metrics shared between KafkaConsumer (v1) and KafkaConsumerV2.
 *
 * Both implementations import these singletons so they can coexist in the same Node.js
 * process during the v2 rollout without registry collisions ("metric X has already been
 * registered"). When v1 is finally deleted, only v2 will reference them — names stay
 * stable so dashboards survive the cutover.
 */

export const kafkaConsumerAssignment = new Gauge({
    name: 'kafka_consumer_assignment',
    help: 'Kafka consumer partition assignment status',
    labelNames: ['topic_name', 'partition_id', 'pod', 'group_id'],
})

export const consumedBatchDuration = new Histogram({
    name: 'consumed_batch_duration_ms',
    help: 'Main loop consumer batch processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

export const consumedBatchBackgroundDuration = new Histogram({
    name: 'consumed_batch_background_duration_ms',
    help: 'Background task processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

export const consumedBatchBackpressureDuration = new Histogram({
    name: 'consumed_batch_backpressure_duration_ms',
    help: 'Time spent waiting for background work to finish due to backpressure',
    labelNames: ['topic', 'groupId'],
})

export const consumerBatchUtilization = new Gauge({
    name: 'consumer_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['groupId'],
})

export const consumerBatchSize = new Histogram({
    name: 'consumer_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

export const consumerBatchSizeKb = new Histogram({
    name: 'consumer_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

// v2-only metrics — kept here for symmetry. v1 doesn't reference these.

export const consumerDrainDuration = new Histogram({
    name: 'kafka_consumer_drain_duration_ms',
    help: 'Time spent draining in-flight tasks during a rebalance or shutdown',
    labelNames: ['topic', 'groupId', 'cause'],
    buckets: [10, 50, 100, 500, 1000, 5000, 10000, 30000, 60000, 120000, Infinity],
})

export const consumerDrainTimeouts = new Counter({
    name: 'kafka_consumer_drain_timeouts_total',
    help: 'Number of times a drain hit its timeout before all tasks settled',
    labelNames: ['topic', 'groupId', 'cause'],
})

export const consumerStaleStoreOffsetsSkipped = new Counter({
    name: 'kafka_consumer_stale_store_offsets_skipped_total',
    help: 'Number of times an offset store was skipped because the task spanned a rebalance generation',
    labelNames: ['topic', 'groupId'],
})
