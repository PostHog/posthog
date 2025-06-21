import { Counter, exponentialBuckets, Histogram, Summary } from 'prom-client'

import { InternalPerson } from '~/types'

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

export const personFetchForCheckingCacheOperationsCounter = new Counter({
    name: 'person_fetch_for_checking_cache_operations_total',
    help: 'Number of operations on the fetchForChecking cache',
    labelNames: ['operation'],
})

export const personFetchForUpdateCacheOperationsCounter = new Counter({
    name: 'person_fetch_for_update_cache_operations_total',
    help: 'Number of operations on the fetchForUpdate cache',
    labelNames: ['operation'],
})

export const personOperationLatencyByVersionSummary = new Summary({
    name: 'person_operation_latency_by_version',
    help: 'Latency distribution of person by version',
    labelNames: ['operation', 'version_bucket'],
})

export const personPropertyKeyUpdateCounter = new Counter({
    name: 'person_property_key_update_total',
    help: 'Number of person updates triggered by this property value changing.',
    labelNames: ['key'],
})

export const personCacheSizeHistogram = new Histogram({
    name: 'person_cache_size',
    help: 'Size of the person cache',
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, Infinity],
})

export const personOptimisticUpdateConflictsPerBatchCounter = new Counter({
    name: 'person_optimistic_update_conflicts_per_batch_total',
    help: 'Number of optimistic update conflicts per batch',
})

// Flush instrumentation metrics
export const personFlushOperationsCounter = new Counter({
    name: 'person_flush_operations_total',
    help: 'Total number of flush operations by outcome',
    labelNames: ['db_write_mode', 'outcome'], // outcome: success, error, fallback
})

export const personFlushLatencyHistogram = new Histogram({
    name: 'person_flush_latency_seconds',
    help: 'Latency of flush operations',
    labelNames: ['db_write_mode'],
    buckets: exponentialBuckets(0.001, 2, 12), // 1ms to ~4s
})

export const personFlushBatchSizeHistogram = new Histogram({
    name: 'person_flush_batch_size',
    help: 'Number of person updates processed in a single flush',
    labelNames: ['db_write_mode'],
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, Infinity],
})

export const personWriteMethodAttemptCounter = new Counter({
    name: 'person_write_method_attempt_total',
    help: 'Number of attempts for each write method',
    labelNames: ['db_write_mode', 'method', 'outcome'], // method: no_assert, assert_version, with_transaction, outcome: success, retry, fallback
})

export const personFallbackOperationsCounter = new Counter({
    name: 'person_fallback_operations_total',
    help: 'Number of fallback operations triggered',
    labelNames: ['db_write_mode', 'fallback_reason'], // fallback_reason: max_retries, error, conflict
})

export const personShadowModeComparisonCounter = new Counter({
    name: 'person_shadow_mode_comparison_total',
    help: 'Person shadow mode comparison results between measuring and batch stores',
    labelNames: ['outcome_type'],
})

export const personShadowModeReturnIntermediateOutcomeCounter = new Counter({
    name: 'person_shadow_mode_return_intermediate_outcome_total',
    help: 'Person shadow mode intermediate comparison results for updatePersonForUpdate and updatePersonForMerge methods',
    labelNames: ['method', 'outcome'],
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
