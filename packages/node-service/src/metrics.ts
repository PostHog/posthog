import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

export interface ServiceMetrics {
    registry: Registry
    httpRequestsTotal: Counter<'method' | 'route' | 'status_code'>
    httpRequestDurationSeconds: Histogram<'method' | 'route' | 'status_code'>
    httpRequestsActive: Gauge<'method'>
    serviceReady: Gauge
    serviceShuttingDown: Gauge
}

export function createServiceMetrics(serviceName: string): ServiceMetrics {
    const registry = new Registry()
    registry.setDefaultLabels({ service: serviceName })
    collectDefaultMetrics({ register: registry, prefix: 'nodejs_' })

    return {
        registry,
        httpRequestsTotal: new Counter({
            name: 'http_server_requests_total',
            help: 'HTTP requests completed by the service.',
            labelNames: ['method', 'route', 'status_code'],
            registers: [registry],
        }),
        httpRequestDurationSeconds: new Histogram({
            name: 'http_server_request_duration_seconds',
            help: 'HTTP request duration in seconds.',
            labelNames: ['method', 'route', 'status_code'],
            buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
            registers: [registry],
        }),
        httpRequestsActive: new Gauge({
            name: 'http_server_active_requests',
            help: 'HTTP requests currently being handled by the service.',
            labelNames: ['method'],
            registers: [registry],
        }),
        serviceReady: new Gauge({
            name: 'nodejs_service_ready',
            help: 'Whether the service is ready to accept traffic.',
            registers: [registry],
        }),
        serviceShuttingDown: new Gauge({
            name: 'nodejs_service_shutting_down',
            help: 'Whether the service is shutting down.',
            registers: [registry],
        }),
    }
}
