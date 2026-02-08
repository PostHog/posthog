// Metrics that make sense across all Kafka consumers
import { Counter, Gauge, Histogram } from 'prom-client'

export const eventDroppedCounter = new Counter({
    name: 'ingestion_event_dropped_total',
    help: 'Count of events dropped by the ingestion pipeline, by type and cause.',
    labelNames: ['event_type', 'drop_cause'],
})

export const cookielessRedisErrorCounter = new Counter({
    name: 'cookieless_redis_error',
    help: 'Count redis errors.',
    labelNames: ['operation'],
})

export const ingestionLagGauge = new Gauge({
    name: 'ingestion_lag_ms',
    help: 'Time difference in ms between event capture time (now header) and ingestion time',
    labelNames: ['topic', 'partition', 'groupId'],
})

export const ingestionLagHistogram = new Histogram({
    name: 'ingestion_lag_ms_histogram',
    help: 'Distribution of ingestion lag per event in ms',
    labelNames: ['groupId', 'partition'],
    buckets: [1000, 2000, 5000, 10000, 30000, 60000, 120000, 300000, 600000, 900000],
})
