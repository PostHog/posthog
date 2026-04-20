import { Counter, Gauge, Histogram } from 'prom-client'

// -- Connection-level metrics --

export const personhogConnectionState = new Gauge({
    name: 'personhog_nodejs_grpc_connection_state',
    help: 'Current gRPC connection state (1 = active state)',
    labelNames: ['state', 'client'] as const,
})

export const personhogConnectionStateTransitionsTotal = new Counter({
    name: 'personhog_nodejs_grpc_connection_state_transitions_total',
    help: 'gRPC connection state transitions',
    labelNames: ['from_state', 'to_state', 'client'] as const,
})

export const personhogConnectionEstablishmentSeconds = new Histogram({
    name: 'personhog_nodejs_grpc_connection_establishment_seconds',
    help: 'Time to establish a gRPC connection (connecting to open/idle)',
    labelNames: ['client'] as const,
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

// -- HTTP/2 stream concurrency metrics --

export const personhogStreamsInFlight = new Gauge({
    name: 'personhog_nodejs_grpc_streams_in_flight',
    help: 'Number of HTTP/2 streams currently open on the gRPC connection',
    labelNames: ['client'] as const,
})

export const personhogStreamAcquisitionSeconds = new Histogram({
    name: 'personhog_nodejs_grpc_stream_acquisition_seconds',
    help: 'Time waiting for an HTTP/2 stream from the session manager (includes connection establishment if needed)',
    labelNames: ['client'] as const,
    buckets: [0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5],
})

// -- Request-level metrics --

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
