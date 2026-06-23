import { Counter, Histogram } from 'prom-client'

export const featureFlagCalledDedupEventsTotal = new Counter({
    name: 'ingestion_feature_flag_called_dedup_events_total',
    help: 'Outcomes of $feature_flag_called dedup claims',
    labelNames: ['outcome'], // 'first_seen' | 'duplicate_dropped' | 'duplicate_shadow'
})

export const featureFlagCalledDedupRedisOpsTotal = new Counter({
    name: 'ingestion_feature_flag_called_dedup_redis_ops_total',
    help: 'Redis operations by the feature flag called dedup service',
    labelNames: ['result'], // 'success' | 'partial_error' | 'error'
})

export const featureFlagCalledDedupRedisLatency = new Histogram({
    name: 'ingestion_feature_flag_called_dedup_redis_latency_seconds',
    help: 'Latency of feature flag called dedup Redis claims in seconds',
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
})
