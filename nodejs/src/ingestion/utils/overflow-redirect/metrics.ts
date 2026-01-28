import { Counter, Gauge, Histogram } from 'prom-client'

// Event processing metrics
export const overflowRedirectEventsTotal = new Counter({
    name: 'overflow_redirect_events_total',
    help: 'Total number of events processed by overflow redirect service',
    labelNames: ['type', 'result'], // result: 'redirected' | 'passed'
})

export const overflowRedirectKeysTotal = new Counter({
    name: 'overflow_redirect_keys_total',
    help: 'Total number of unique keys processed by overflow redirect service',
    labelNames: ['type', 'result'], // result: 'redirected' | 'passed'
})

// Redis operation metrics
export const overflowRedirectRedisOpsTotal = new Counter({
    name: 'overflow_redirect_redis_ops_total',
    help: 'Total number of Redis operations by overflow redirect service',
    labelNames: ['operation', 'result'], // operation: 'mget' | 'set' | 'getex', result: 'success' | 'error'
})

export const overflowRedirectRedisLatency = new Histogram({
    name: 'overflow_redirect_redis_latency_seconds',
    help: 'Latency of Redis operations in seconds',
    labelNames: ['operation'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
})

// Cache metrics
export const overflowRedirectCacheHitsTotal = new Counter({
    name: 'overflow_redirect_cache_hits_total',
    help: 'Total number of local cache hits',
    labelNames: ['type', 'result'], // result: 'hit_flagged' | 'hit_not_flagged' | 'miss'
})

export const overflowRedirectCacheSize = new Gauge({
    name: 'overflow_redirect_cache_size',
    help: 'Current size of the local cache',
})

// Rate limiter metrics
export const overflowRedirectRateLimitDecisions = new Counter({
    name: 'overflow_redirect_rate_limit_decisions_total',
    help: 'Total number of rate limit decisions',
    labelNames: ['type', 'decision'], // decision: 'allowed' | 'exceeded'
})
