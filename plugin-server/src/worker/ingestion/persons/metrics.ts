import { Histogram } from 'prom-client'

export const personMethodCallsPerBatchHistogram = new Histogram({
    name: 'person_method_calls_per_batch',
    help: 'Number of calls to each person store method per distinct ID per batch',
    labelNames: ['method'],
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})
