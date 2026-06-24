import { Counter, Histogram } from 'prom-client'

export const groupDatabaseOperationsPerBatchHistogram = new Histogram({
    name: 'group_database_operations_per_batch',
    help: 'Number of database operations per distinct ID per batch',
    labelNames: ['operation'],
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})

export const groupCacheOperationsCounter = new Counter({
    name: 'group_cache_operations_total',
    help: 'Total number of cache hits and misses',
    labelNames: ['operation'],
})

export const groupOptimisticUpdateConflictsPerBatchCounter = new Counter({
    name: 'group_optimistic_update_conflicts_per_batch',
    help: 'Number of optimistic update conflicts for groups per batch',
})

export const groupCacheSizeHistogram = new Histogram({
    name: 'group_cache_size',
    help: 'Size of the group cache',
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})

export const groupFetchPromisesCacheOperationsCounter = new Counter({
    name: 'group_fetch_promises_cache_operations_total',
    help: 'Number of operations on the fetchPromises cache',
    labelNames: ['operation'],
})
