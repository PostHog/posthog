/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const DependencyKindEnumApi = zod
    .enum(['service', 'database', 'queue', 'external'])
    .describe('\* `service` - Service\n\* `database` - Database\n\* `queue` - Queue\n\* `external` - External')

export type DependencyKindEnumApi = zod.input<typeof DependencyKindEnumApi>
export type DependencyKindEnumApiOutput = zod.output<typeof DependencyKindEnumApi>

export const DependencyEdgeApi = zod.object({
    caller: zod.string().describe('The calling service.'),
    callee: zod
        .string()
        .describe(
            'The called service, or for an inferred dependency the peer service, database, queue or host it names.'
        ),
    inferred: zod
        .boolean()
        .describe("True when the callee sends no spans and is named by the caller's client span attributes."),
    kind: zod
        .enum(['service', 'database', 'queue', 'external'])
        .describe('\* `service` - Service\n\* `database` - Database\n\* `queue` - Queue\n\* `external` - External')
        .describe(
            'What the callee is.\n\n\* `service` - Service\n\* `database` - Database\n\* `queue` - Queue\n\* `external` - External'
        ),
    requests: zod.number().describe('Calls from the caller into the callee in the window.'),
    error_count: zod.number().describe("Calls with an error status, on the caller's client span when it has one."),
    p95_ms: zod
        .number()
        .nullable()
        .describe("95th percentile call duration in ms, on the caller's client span when it has one."),
})

export type DependencyEdgeApi = zod.input<typeof DependencyEdgeApi>
export type DependencyEdgeApiOutput = zod.output<typeof DependencyEdgeApi>

export const DependenciesResponseApi = zod.object({
    edges: zod
        .array(
            zod.object({
                caller: zod.string().describe('The calling service.'),
                callee: zod
                    .string()
                    .describe(
                        'The called service, or for an inferred dependency the peer service, database, queue or host it names.'
                    ),
                inferred: zod
                    .boolean()
                    .describe(
                        "True when the callee sends no spans and is named by the caller's client span attributes."
                    ),
                kind: zod
                    .enum(['service', 'database', 'queue', 'external'])
                    .describe(
                        '\* `service` - Service\n\* `database` - Database\n\* `queue` - Queue\n\* `external` - External'
                    )
                    .describe(
                        'What the callee is.\n\n\* `service` - Service\n\* `database` - Database\n\* `queue` - Queue\n\* `external` - External'
                    ),
                requests: zod.number().describe('Calls from the caller into the callee in the window.'),
                error_count: zod
                    .number()
                    .describe("Calls with an error status, on the caller's client span when it has one."),
                p95_ms: zod
                    .number()
                    .nullable()
                    .describe("95th percentile call duration in ms, on the caller's client span when it has one."),
            })
        )
        .describe('One edge per caller and callee, most requests first.'),
    truncated: zod.boolean().describe('True when more edges matched than the response holds.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the edges were computed for: null for every environment, empty for spans with no environment.'
        ),
    service: zod.string().nullable().describe('The service filter applied, if any.'),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type DependenciesResponseApi = zod.input<typeof DependenciesResponseApi>
export type DependenciesResponseApiOutput = zod.output<typeof DependenciesResponseApi>

export const DeploymentVersionApi = zod.object({
    version: zod.string().describe('The service.version resource attribute.'),
    first_seen: zod.iso.datetime({ offset: true }).describe('First span of this version in the window.'),
    last_seen: zod.iso.datetime({ offset: true }).describe('Last span of this version in the window.'),
    requests: zod.number().describe('Requests counted in the window.'),
    error_count: zod.number().describe('Requests with an error status.'),
    error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
    p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
    previous_version: zod
        .string()
        .nullable()
        .describe('The version first seen just before this one. Null for the oldest.'),
    error_rate_change: zod.number().nullable().describe("Error rate minus the previous version's, as a fraction."),
    p95_change_pct: zod.number().nullable().describe('Change in p95 from the previous version, in percent.'),
    active: zod.boolean().describe('True for the version first seen most recently.'),
})

export type DeploymentVersionApi = zod.input<typeof DeploymentVersionApi>
export type DeploymentVersionApiOutput = zod.output<typeof DeploymentVersionApi>

export const DeploymentsResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                version: zod.string().describe('The service.version resource attribute.'),
                first_seen: zod.iso.datetime({ offset: true }).describe('First span of this version in the window.'),
                last_seen: zod.iso.datetime({ offset: true }).describe('Last span of this version in the window.'),
                requests: zod.number().describe('Requests counted in the window.'),
                error_count: zod.number().describe('Requests with an error status.'),
                error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
                p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
                previous_version: zod
                    .string()
                    .nullable()
                    .describe('The version first seen just before this one. Null for the oldest.'),
                error_rate_change: zod
                    .number()
                    .nullable()
                    .describe("Error rate minus the previous version's, as a fraction."),
                p95_change_pct: zod
                    .number()
                    .nullable()
                    .describe('Change in p95 from the previous version, in percent.'),
                active: zod.boolean().describe('True for the version first seen most recently.'),
            })
        )
        .describe('One row per version, oldest first.'),
    service: zod.string().describe('The service the versions belong to.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the rows were computed for: null for every environment, empty for spans with no environment.'
        ),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type DeploymentsResponseApi = zod.input<typeof DeploymentsResponseApi>
export type DeploymentsResponseApiOutput = zod.output<typeof DeploymentsResponseApi>

export const TimeSpentComponentKindEnumApi = zod
    .enum(['service', 'inferred', 'other'])
    .describe('\* `service` - Service\n\* `inferred` - Inferred\n\* `other` - Other')

export type TimeSpentComponentKindEnumApi = zod.input<typeof TimeSpentComponentKindEnumApi>
export type TimeSpentComponentKindEnumApiOutput = zod.output<typeof TimeSpentComponentKindEnumApi>

export const TimeSpentComponentApi = zod.object({
    name: zod
        .string()
        .describe("The service name, the inferred dependency (for example a database system or host), or 'Other'."),
    kind: zod
        .enum(['service', 'inferred', 'other'])
        .describe('\* `service` - Service\n\* `inferred` - Inferred\n\* `other` - Other')
        .describe(
            'service: an instrumented service. inferred: a dependency seen only through client spans. other: the remaining components combined.\n\n\* `service` - Service\n\* `inferred` - Inferred\n\* `other` - Other'
        ),
    total_ms: zod.number().describe('Self-time summed across the sampled requests, in milliseconds.'),
    avg_ms_per_request: zod.number().describe('Self-time per sampled request, in milliseconds.'),
    share: zod.number().describe('Share of the attributed request time, 0 to 1.'),
})

export type TimeSpentComponentApi = zod.input<typeof TimeSpentComponentApi>
export type TimeSpentComponentApiOutput = zod.output<typeof TimeSpentComponentApi>

export const EndpointTimeSpentResponseApi = zod.object({
    components: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .describe(
                        "The service name, the inferred dependency (for example a database system or host), or 'Other'."
                    ),
                kind: zod
                    .enum(['service', 'inferred', 'other'])
                    .describe('\* `service` - Service\n\* `inferred` - Inferred\n\* `other` - Other')
                    .describe(
                        'service: an instrumented service. inferred: a dependency seen only through client spans. other: the remaining components combined.\n\n\* `service` - Service\n\* `inferred` - Inferred\n\* `other` - Other'
                    ),
                total_ms: zod.number().describe('Self-time summed across the sampled requests, in milliseconds.'),
                avg_ms_per_request: zod.number().describe('Self-time per sampled request, in milliseconds.'),
                share: zod.number().describe('Share of the attributed request time, 0 to 1.'),
            })
        )
        .describe('Where the request time goes, largest share first.'),
    request_count: zod.number().describe('Requests sampled to compute the breakdown.'),
    avg_duration_ms: zod.number().nullable().describe('Mean duration of the sampled requests, in milliseconds.'),
    service: zod.string().describe('The service the endpoint belongs to.'),
    endpoint: zod.string().describe("The endpoint's entry span name."),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the breakdown was computed for: null for every environment, empty for spans with no environment.'
        ),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type EndpointTimeSpentResponseApi = zod.input<typeof EndpointTimeSpentResponseApi>
export type EndpointTimeSpentResponseApiOutput = zod.output<typeof EndpointTimeSpentResponseApi>

export const HealthStatusEnumApi = zod
    .enum(['good', 'warning', 'serious', 'critical'])
    .describe('\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical')

export type HealthStatusEnumApi = zod.input<typeof HealthStatusEnumApi>
export type HealthStatusEnumApiOutput = zod.output<typeof HealthStatusEnumApi>

export const HealthRowApi = zod.object({
    request_rate: zod.number().nullable().describe('Requests per second over the window.'),
    error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
    p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
    span_count: zod.number().describe('Requests counted in the window.'),
    error_count: zod.number().describe('Requests with an error status in the window.'),
})

export type HealthRowApi = zod.input<typeof HealthRowApi>
export type HealthRowApiOutput = zod.output<typeof HealthRowApi>

export const EndpointHealthApi = zod.object({
    service_name: zod.string().describe('The service.name resource attribute.'),
    endpoint: zod
        .string()
        .describe(
            'The endpoint label: the entry span name, or \"<METHOD> <route>\" when the span name is only an HTTP method and the span carries a route.'
        ),
    span_name: zod.string().describe('The raw entry span name the row counts, for tracing filters.'),
    route_attribute: zod
        .string()
        .nullable()
        .describe(
            'The span attribute the route came from (http.route or url.template), or null when the label is the span name.'
        ),
    route: zod.string().nullable().describe('The route appended to the span name, or null.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the row was computed for: null for every environment, empty for spans with no environment.'
        ),
    status: zod
        .enum(['good', 'warning', 'serious', 'critical'])
        .describe('\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical')
        .describe(
            'Health band from the error rate.\n\n\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
        ),
    health: zod
        .object({
            request_rate: zod.number().nullable().describe('Requests per second over the window.'),
            error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
            p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
            span_count: zod.number().describe('Requests counted in the window.'),
            error_count: zod.number().describe('Requests with an error status in the window.'),
        })
        .describe('The health row every surface renders.'),
})

export type EndpointHealthApi = zod.input<typeof EndpointHealthApi>
export type EndpointHealthApiOutput = zod.output<typeof EndpointHealthApi>

export const EndpointsHealthResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                service_name: zod.string().describe('The service.name resource attribute.'),
                endpoint: zod
                    .string()
                    .describe(
                        'The endpoint label: the entry span name, or \"<METHOD> <route>\" when the span name is only an HTTP method and the span carries a route.'
                    ),
                span_name: zod.string().describe('The raw entry span name the row counts, for tracing filters.'),
                route_attribute: zod
                    .string()
                    .nullable()
                    .describe(
                        'The span attribute the route came from (http.route or url.template), or null when the label is the span name.'
                    ),
                route: zod.string().nullable().describe('The route appended to the span name, or null.'),
                environment: zod
                    .string()
                    .nullable()
                    .describe(
                        'The environment filter the row was computed for: null for every environment, empty for spans with no environment.'
                    ),
                status: zod
                    .enum(['good', 'warning', 'serious', 'critical'])
                    .describe(
                        '\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
                    )
                    .describe(
                        'Health band from the error rate.\n\n\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
                    ),
                health: zod
                    .object({
                        request_rate: zod.number().nullable().describe('Requests per second over the window.'),
                        error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
                        p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
                        span_count: zod.number().describe('Requests counted in the window.'),
                        error_count: zod.number().describe('Requests with an error status in the window.'),
                    })
                    .describe('The health row every surface renders.'),
            })
        )
        .describe('One row per service and endpoint, worst status first.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the rows were computed for: null for every environment, empty for spans with no environment.'
        ),
    service: zod.string().nullable().describe('The service filter applied, if any.'),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type EndpointsHealthResponseApi = zod.input<typeof EndpointsHealthResponseApi>
export type EndpointsHealthResponseApiOutput = zod.output<typeof EndpointsHealthResponseApi>

export const ServiceEdgeApi = zod.object({
    caller: zod.string().describe('The calling service.'),
    callee: zod.string().describe('The called service.'),
    calls: zod.number().describe('Calls from the caller into the callee in the sampled traces.'),
    error_count: zod.number().describe('Calls with an error status on the callee span.'),
    p95_ms: zod.number().nullable().describe('95th percentile duration of the callee span, in ms.'),
})

export type ServiceEdgeApi = zod.input<typeof ServiceEdgeApi>
export type ServiceEdgeApiOutput = zod.output<typeof ServiceEdgeApi>

export const ServiceMapResponseApi = zod.object({
    edges: zod
        .array(
            zod.object({
                caller: zod.string().describe('The calling service.'),
                callee: zod.string().describe('The called service.'),
                calls: zod.number().describe('Calls from the caller into the callee in the sampled traces.'),
                error_count: zod.number().describe('Calls with an error status on the callee span.'),
                p95_ms: zod.number().nullable().describe('95th percentile duration of the callee span, in ms.'),
            })
        )
        .describe('One edge per calling and called service, most calls first.'),
    trace_count: zod.number().describe('Traces sampled to build the map.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the map was built for: null for every environment, empty for spans with no environment.'
        ),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type ServiceMapResponseApi = zod.input<typeof ServiceMapResponseApi>
export type ServiceMapResponseApiOutput = zod.output<typeof ServiceMapResponseApi>

export const ServiceHealthApi = zod.object({
    service_name: zod.string().describe('The service.name resource attribute.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the row was computed for: null for every environment, empty for spans with no environment.'
        ),
    status: zod
        .enum(['good', 'warning', 'serious', 'critical'])
        .describe('\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical')
        .describe(
            'Health band from the error rate.\n\n\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
        ),
    health: zod
        .object({
            request_rate: zod.number().nullable().describe('Requests per second over the window.'),
            error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
            p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
            span_count: zod.number().describe('Requests counted in the window.'),
            error_count: zod.number().describe('Requests with an error status in the window.'),
        })
        .describe('The health row every surface renders.'),
    sparkline: zod.array(zod.number()).describe('Request counts per bucket across the window, oldest first.'),
})

export type ServiceHealthApi = zod.input<typeof ServiceHealthApi>
export type ServiceHealthApiOutput = zod.output<typeof ServiceHealthApi>

export const ServicesHealthResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                service_name: zod.string().describe('The service.name resource attribute.'),
                environment: zod
                    .string()
                    .nullable()
                    .describe(
                        'The environment filter the row was computed for: null for every environment, empty for spans with no environment.'
                    ),
                status: zod
                    .enum(['good', 'warning', 'serious', 'critical'])
                    .describe(
                        '\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
                    )
                    .describe(
                        'Health band from the error rate.\n\n\* `good` - Good\n\* `warning` - Warning\n\* `serious` - Serious\n\* `critical` - Critical'
                    ),
                health: zod
                    .object({
                        request_rate: zod.number().nullable().describe('Requests per second over the window.'),
                        error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
                        p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
                        span_count: zod.number().describe('Requests counted in the window.'),
                        error_count: zod.number().describe('Requests with an error status in the window.'),
                    })
                    .describe('The health row every surface renders.'),
                sparkline: zod
                    .array(zod.number())
                    .describe('Request counts per bucket across the window, oldest first.'),
            })
        )
        .describe('One row per service, worst status first.'),
    environments: zod
        .array(zod.string().nullable())
        .describe('Environments seen in the window. Null stands for spans that set no environment.'),
    environment: zod
        .string()
        .nullable()
        .describe(
            'The environment filter the rows were computed for: null for every environment, empty for spans with no environment.'
        ),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type ServicesHealthResponseApi = zod.input<typeof ServicesHealthResponseApi>
export type ServicesHealthResponseApiOutput = zod.output<typeof ServicesHealthResponseApi>

export const ServiceUsageApi = zod.object({
    log_records: zod.number().describe('Log records stored in the window.'),
    log_bytes: zod
        .number()
        .describe('Uncompressed size of the stored log records in bytes. Billing counts logs by this size.'),
    spans: zod.number().describe('Spans of every kind stored in the window.'),
    metric_points: zod.number().describe('Metric data points stored in the window.'),
    metric_series: zod.number().describe('Distinct metric series with at least one point in the window.'),
    service_name: zod.string().describe('The service.name resource attribute.'),
})

export type ServiceUsageApi = zod.input<typeof ServiceUsageApi>
export type ServiceUsageApiOutput = zod.output<typeof ServiceUsageApi>

export const UsageValuesApi = zod.object({
    log_records: zod.number().describe('Log records stored in the window.'),
    log_bytes: zod
        .number()
        .describe('Uncompressed size of the stored log records in bytes. Billing counts logs by this size.'),
    spans: zod.number().describe('Spans of every kind stored in the window.'),
    metric_points: zod.number().describe('Metric data points stored in the window.'),
    metric_series: zod.number().describe('Distinct metric series with at least one point in the window.'),
})

export type UsageValuesApi = zod.input<typeof UsageValuesApi>
export type UsageValuesApiOutput = zod.output<typeof UsageValuesApi>

export const UsageSignalEnumApi = zod
    .enum(['logs', 'traces', 'metrics'])
    .describe('\* `logs` - Logs\n\* `traces` - Traces\n\* `metrics` - Metrics')

export type UsageSignalEnumApi = zod.input<typeof UsageSignalEnumApi>
export type UsageSignalEnumApiOutput = zod.output<typeof UsageSignalEnumApi>

export const ServiceUsageResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                log_records: zod.number().describe('Log records stored in the window.'),
                log_bytes: zod
                    .number()
                    .describe(
                        'Uncompressed size of the stored log records in bytes. Billing counts logs by this size.'
                    ),
                spans: zod.number().describe('Spans of every kind stored in the window.'),
                metric_points: zod.number().describe('Metric data points stored in the window.'),
                metric_series: zod.number().describe('Distinct metric series with at least one point in the window.'),
                service_name: zod.string().describe('The service.name resource attribute.'),
            })
        )
        .describe('One row per service across logs, traces, and metrics, largest logs size first.'),
    totals: zod
        .object({
            log_records: zod.number().describe('Log records stored in the window.'),
            log_bytes: zod
                .number()
                .describe('Uncompressed size of the stored log records in bytes. Billing counts logs by this size.'),
            spans: zod.number().describe('Spans of every kind stored in the window.'),
            metric_points: zod.number().describe('Metric data points stored in the window.'),
            metric_series: zod.number().describe('Distinct metric series with at least one point in the window.'),
        })
        .describe('Totals for the whole window, including services past the row limit.'),
    unavailable_signals: zod
        .array(
            zod
                .enum(['logs', 'traces', 'metrics'])
                .describe('\* `logs` - Logs\n\* `traces` - Traces\n\* `metrics` - Metrics')
        )
        .describe('Signals that failed to load. Their values are 0 in every row and in the totals.'),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type ServiceUsageResponseApi = zod.input<typeof ServiceUsageResponseApi>
export type ServiceUsageResponseApiOutput = zod.output<typeof ServiceUsageResponseApi>
