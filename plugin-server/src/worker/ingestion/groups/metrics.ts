import { Counter } from 'prom-client'

export const groupCacheOperationsCounter = new Counter({
    name: 'group_cache_operations_total',
    help: 'Total number of cache hits and misses',
    labelNames: ['operation'],
})

export const groupCacheSizeCounter = new Counter({
    name: 'group_cache_size',
    help: 'Size of the group cache',
})
