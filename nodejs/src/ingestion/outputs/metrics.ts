import { Counter, Histogram } from 'prom-client'

export const ingestionOutputsMessageValueBytes = new Histogram({
    name: 'ingestion_outputs_message_value_bytes',
    help: 'Approximate value size in bytes per message produced to ingestion outputs',
    labelNames: ['output'],
    // 128B, 256B, 512B, 1KB, 2KB, 4KB, 8KB, 16KB, 32KB, 64KB, 128KB, 256KB, 512KB, 1MB, 2MB, 4MB, 8MB, 16MB, 32MB, 64MB
    buckets: [
        128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4194304,
        8388608, 16777216, 33554432, 67108864,
    ],
})

export const ingestionOutputsLatency = new Histogram({
    name: 'ingestion_outputs_latency_seconds',
    help: 'Latency of produce/queueMessages calls to ingestion outputs',
    labelNames: ['output', 'method'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

export const ingestionOutputsErrors = new Counter({
    name: 'ingestion_outputs_errors_total',
    help: 'Total number of produce/queueMessages errors on ingestion outputs',
    labelNames: ['output', 'method'],
})

export const ingestionOutputsBatchSize = new Histogram({
    name: 'ingestion_outputs_batch_size',
    help: 'Number of messages per produce/queueMessages call',
    labelNames: ['output', 'method'],
    buckets: [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000],
})
