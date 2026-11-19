import type { Usage } from './api'

export const SAMPLE_USAGE: Usage = {
    dashboards: 14,
    metrics: {
        http_requests_total: 9,
        http_request_duration_seconds_bucket: 7,
        container_memory_working_set_bytes: 4,
        queue_depth: 3,
        db_connections_active: 2,
    },
    labels: { service: 11, status: 6, region: 5, method: 3, queue: 2, pod: 2 },
    values: {
        service: { api: 6, checkout: 3, ingest: 2 },
        status: { '500': 3, '503': 2, '200': 2 },
        region: { 'us-east-1': 4, 'eu-central-1': 2 },
        queue: { ingestion: 2, exports: 1 },
        'k8s.namespace.name': { app: 3, payments: 2 },
        'deployment.environment.name': { production: 4 },
        'http.status_code': { '500': 2 },
    },
    services: { api: 5, checkout: 3, ingest: 2 },
    attributes: {
        'k8s.namespace.name': 4,
        'http.status_code': 3,
        'deployment.environment.name': 2,
        'error.type': 2,
    },
}

export const SAMPLE_METRIC_USAGE: Record<string, Record<string, number>> = {
    http_requests_total: { service: 8, status: 6, method: 3, region: 2 },
    http_request_duration_seconds_bucket: { service: 6, region: 3, method: 2 },
    container_memory_working_set_bytes: { namespace: 3, pod: 3, container: 1 },
    queue_depth: { queue: 3, service: 1 },
    db_connections_active: { db: 2, pool: 2, service: 1 },
}
