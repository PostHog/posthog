import { Counter, Histogram } from 'prom-client'

export const personhogRequestsTotal = new Counter({
    name: 'personhog_requests_total',
    help: 'Total PersonHog group repository requests',
    labelNames: ['method', 'source', 'client'] as const,
})

export const personhogErrorsTotal = new Counter({
    name: 'personhog_errors_total',
    help: 'Total PersonHog gRPC errors (before fallback to Postgres)',
    labelNames: ['method', 'client'] as const,
})

export const personhogLatencySeconds = new Histogram({
    name: 'personhog_latency_seconds',
    help: 'PersonHog request latency in seconds',
    labelNames: ['method', 'source', 'client'] as const,
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5],
})
