import { Counter, Histogram, exponentialBuckets } from 'prom-client'

const STORE_LABELS = ['store'] as const
const STORE_OUTCOME_LABELS = ['store', 'outcome'] as const

export const batchStoreFlushOperationsCounter = new Counter({
    name: 'batch_store_flush_operations_total',
    help: 'Total number of batch store flush operations by store and outcome',
    labelNames: STORE_OUTCOME_LABELS,
})

export const batchStoreFlushLatencyHistogram = new Histogram({
    name: 'batch_store_flush_latency_seconds',
    help: 'Latency of batch store flush operations',
    labelNames: STORE_OUTCOME_LABELS,
    buckets: exponentialBuckets(0.001, 2, 12),
})

export const batchStoreFlushTriggerBatchSizeHistogram = new Histogram({
    name: 'batch_store_flush_trigger_batch_size',
    help: 'Number of pipeline results in the completed batch that triggered a batch store flush',
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})

export const batchStoreFlushDirtyEntriesHistogram = new Histogram({
    name: 'batch_store_flush_dirty_entries',
    help: 'Number of dirty cache entries captured at batch store flush start',
    labelNames: STORE_LABELS,
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})

export const batchStoreFlushReferencedBatchesHistogram = new Histogram({
    name: 'batch_store_flush_referenced_batches',
    help: 'Number of batch IDs that reference dirty cache entries at batch store flush start',
    labelNames: STORE_LABELS,
    buckets: [0, 1, 2, 3, 4, 5, 10, 20, 50, 100],
})

export const batchStoreFlushCacheEntriesHistogram = new Histogram({
    name: 'batch_store_flush_cache_entries',
    help: 'Number of cache entries present at batch store flush start',
    labelNames: STORE_LABELS,
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})

export const batchStoreFlushResultRecordsHistogram = new Histogram({
    name: 'batch_store_flush_result_records',
    help: 'Number of flush result records returned by a batch store flush',
    labelNames: STORE_LABELS,
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})

export const batchStoreFlushKafkaMessagesHistogram = new Histogram({
    name: 'batch_store_flush_kafka_messages',
    help: 'Number of Kafka messages returned by a batch store flush for side-effect production',
    labelNames: STORE_LABELS,
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})
