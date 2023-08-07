import { Counter, exponentialBuckets, Histogram } from 'prom-client' // but fail to commit offsets, which can cause duplicate events

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
