import { Counter, Histogram, Summary, exponentialBuckets } from 'prom-client'

// The following two counters can be used to see how often we start,
// but fail to commit offsets, which can cause duplicate events
export const kafkaBatchStart = new Counter({
    name: 'ingestion_kafka_batch_start',
    help: 'Number of times we have started working on a kafka batch',
})
export const kafkaBatchOffsetCommitted = new Counter({
    name: 'ingestion_kafka_batch_committed_offsets',
    help: 'Number of times we have committed kafka offsets',
})

export const ingestionOverflowingMessagesTotal = new Counter({
    name: 'ingestion_overflowing_messages_total',
    help: 'Count of messages rerouted to the overflow topic.',
})

export const ingestionParallelism = new Histogram({
    name: 'ingestion_batch_parallelism',
    help: 'Processing parallelism per ingestion consumer batch',
    labelNames: ['overflow_mode'],
    buckets: exponentialBuckets(1, 2, 7), // Up to 64
})

export const ingestionParallelismPotential = new Histogram({
    name: 'ingestion_batch_parallelism_potential',
    help: 'Number of eligible parts per ingestion consumer batch',
    labelNames: ['overflow_mode'],
    buckets: exponentialBuckets(1, 2, 7), // Up to 64
})

export const ingestEventBatchingInputLengthSummary = new Summary({
    name: 'ingest_event_batching_input_length',
    help: 'Length of input batches of events',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const ingestEventBatchingBatchCountSummary = new Summary({
    name: 'ingest_event_batching_batch_count',
    help: 'Number of batches of events',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const ingestEventBatchingDistinctIdBatchLengthSummary = new Summary({
    name: 'ingest_event_batching_distinct_id_batch_length',
    help: 'Length of input batches of events per distinct ID',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const ingestEventEachBatchKafkaAckWait = new Summary({
    name: 'ingest_event_each_batch_kafka_ack_wait',
    help: 'Wait time for the batch of Kafka ACKs at the end of eachBatchParallelIngestion',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
