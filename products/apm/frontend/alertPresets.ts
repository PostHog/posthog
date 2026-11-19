import type { TracesAlertPresetTarget } from 'products/tracing/frontend/alerting/tracesAlertPresets'

import type { EndpointHealthApi, ServiceHealthApi } from './generated/api.schemas'

export function serviceAlertTarget(row: ServiceHealthApi): TracesAlertPresetTarget {
    return {
        serviceName: row.service_name,
        operation: null,
        requestCount: row.health.span_count,
        errorCount: row.health.error_count,
        p95Ms: row.health.p95_ms,
    }
}

export function endpointAlertTarget(row: EndpointHealthApi): TracesAlertPresetTarget {
    return {
        serviceName: row.service_name,
        operation: row.span_name,
        label: row.endpoint,
        route:
            row.route_attribute !== null && row.route !== null
                ? { attribute: row.route_attribute, value: row.route }
                : null,
        requestCount: row.health.span_count,
        errorCount: row.health.error_count,
        p95Ms: row.health.p95_ms,
    }
}
