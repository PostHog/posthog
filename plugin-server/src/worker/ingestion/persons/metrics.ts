import { Counter, exponentialBuckets, Histogram, Summary } from 'prom-client'

import { InternalPerson } from '~/src/types'

export const personMethodCallsPerBatchHistogram = new Histogram({
    name: 'person_method_calls_per_batch',
    help: 'Number of calls to each person store method per distinct ID per batch',
    labelNames: ['method'],
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})

export const personDatabaseOperationsPerBatchHistogram = new Histogram({
    name: 'person_database_operations_per_batch',
    help: 'Number of database operations per distinct ID per batch',
    labelNames: ['operation'],
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})

export const totalPersonUpdateLatencyPerBatchHistogram = new Histogram({
    name: 'total_person_update_latency_per_batch_seconds',
    help: 'Total latency of person update per distinct ID per batch',
    labelNames: ['update_type'],
    buckets: exponentialBuckets(0.025, 4, 7),
})

export const personCacheOperationsCounter = new Counter({
    name: 'person_cache_operations_total',
    help: 'Total number of cache hits and misses',
    labelNames: ['cache', 'operation'],
})

export const personOperationLatencyByVersionSummary = new Summary({
    name: 'person_operation_latency_by_version',
    help: 'Latency distribution of person by version',
    labelNames: ['operation', 'version_bucket'],
})

export function getVersionBucketLabel(version: number): string {
    if (version === 0) {
        return 'v0'
    }
    if (version <= 50) {
        return 'v1-50'
    }
    if (version <= 100) {
        return 'v51-100'
    }
    if (version <= 1000) {
        return 'v101-1000'
    }
    if (version <= 10000) {
        return 'v1001-10000'
    }
    if (version <= 100000) {
        return 'v10001-100000'
    }
    if (version <= 1000000) {
        return 'v100001-1000000'
    }
    return 'v1000001+'
}

export function observeLatencyByVersion(person: InternalPerson | undefined, start: number, operation: string) {
    if (!person) {
        return
    }
    const versionBucket = getVersionBucketLabel(person.version)
    personOperationLatencyByVersionSummary.labels(operation, versionBucket).observe(performance.now() - start)
}
