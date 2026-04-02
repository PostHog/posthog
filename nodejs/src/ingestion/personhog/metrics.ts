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

export async function timedPostgres<T>(clientLabel: string, method: string, fn: () => Promise<T>): Promise<T> {
    const end = personhogLatencySeconds.startTimer({ method, source: 'postgres', client: clientLabel })
    try {
        return await fn()
    } finally {
        end()
        personhogRequestsTotal.inc({ method, source: 'postgres', client: clientLabel })
    }
}

export async function timedGrpc<T>(clientLabel: string, method: string, fn: () => Promise<T>): Promise<T> {
    const end = personhogLatencySeconds.startTimer({ method, source: 'grpc', client: clientLabel })
    try {
        return await fn()
    } catch (error) {
        personhogErrorsTotal.inc({ method, client: clientLabel })
        throw error
    } finally {
        end()
        personhogRequestsTotal.inc({ method, source: 'grpc', client: clientLabel })
    }
}
