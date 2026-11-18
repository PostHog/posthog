/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `service` - Service
 * * `database` - Database
 * * `queue` - Queue
 * * `external` - External
 */
export type DependencyKindEnumApi = (typeof DependencyKindEnumApi)[keyof typeof DependencyKindEnumApi]

export const DependencyKindEnumApi = {
    Service: 'service',
    Database: 'database',
    Queue: 'queue',
    External: 'external',
} as const

export interface DependencyEdgeApi {
    /** The calling service. */
    caller: string
    /** The called service, or for an inferred dependency the peer service, database, queue or host it names. */
    callee: string
    /** True when the callee sends no spans and is named by the caller's client span attributes. */
    inferred: boolean
    /** What the callee is.
     *
     * * `service` - Service
     * * `database` - Database
     * * `queue` - Queue
     * * `external` - External */
    kind: DependencyKindEnumApi
    /** Calls from the caller into the callee in the window. */
    requests: number
    /** Calls with an error status, on the caller's client span when it has one. */
    error_count: number
    /**
     * 95th percentile call duration in ms, on the caller's client span when it has one.
     * @nullable
     */
    p95_ms: number | null
}

export interface DependenciesResponseApi {
    /** One edge per caller and callee, most requests first. */
    edges: DependencyEdgeApi[]
    /** True when more edges matched than the response holds. */
    truncated: boolean
    /**
     * The environment filter the edges were computed for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /**
     * The service filter applied, if any.
     * @nullable
     */
    service: string | null
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

/**
 * * `good` - Good
 * * `warning` - Warning
 * * `serious` - Serious
 * * `critical` - Critical
 */
export type HealthStatusEnumApi = (typeof HealthStatusEnumApi)[keyof typeof HealthStatusEnumApi]

export const HealthStatusEnumApi = {
    Good: 'good',
    Warning: 'warning',
    Serious: 'serious',
    Critical: 'critical',
} as const

export interface HealthRowApi {
    /**
     * Requests per second over the window.
     * @nullable
     */
    request_rate: number | null
    /**
     * Share of requests with an error status, 0 to 1.
     * @nullable
     */
    error_rate: number | null
    /**
     * 95th percentile request duration in milliseconds.
     * @nullable
     */
    p95_ms: number | null
    /** Requests counted in the window. */
    span_count: number
    /** Requests with an error status in the window. */
    error_count: number
    /**
     * Apdex score from 0 to 1 with a 500 ms threshold: satisfied requests plus half the tolerating ones (up to 2 s), over all requests. Errors count as frustrated.
     * @nullable
     */
    apdex: number | null
}

export interface EndpointHealthApi {
    /** The service.name resource attribute. */
    service_name: string
    /** The entry span name, for example the HTTP route or the job name. */
    endpoint: string
    /**
     * The environment filter the row was computed for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /** Health band from the error rate.
     *
     * * `good` - Good
     * * `warning` - Warning
     * * `serious` - Serious
     * * `critical` - Critical */
    status: HealthStatusEnumApi
    /** The health row every surface renders. */
    health: HealthRowApi
}

export interface EndpointsHealthResponseApi {
    /** One row per service and endpoint, worst status first. */
    results: EndpointHealthApi[]
    /**
     * The environment filter the rows were computed for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /**
     * The service filter applied, if any.
     * @nullable
     */
    service: string | null
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

export interface ServiceEdgeApi {
    /** The calling service. */
    caller: string
    /** The called service. */
    callee: string
    /** Calls from the caller into the callee in the sampled traces. */
    calls: number
    /** Calls with an error status on the callee span. */
    error_count: number
    /**
     * 95th percentile duration of the callee span, in ms.
     * @nullable
     */
    p95_ms: number | null
}

export interface ServiceMapResponseApi {
    /** One edge per calling and called service, most calls first. */
    edges: ServiceEdgeApi[]
    /** Traces sampled to build the map. */
    trace_count: number
    /**
     * The environment filter the map was built for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

export interface ServiceHealthApi {
    /** The service.name resource attribute. */
    service_name: string
    /**
     * The environment filter the row was computed for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /** Health band from the error rate.
     *
     * * `good` - Good
     * * `warning` - Warning
     * * `serious` - Serious
     * * `critical` - Critical */
    status: HealthStatusEnumApi
    /** The health row every surface renders. */
    health: HealthRowApi
    /** Request counts per bucket across the window, oldest first. */
    sparkline: number[]
}

export interface ServicesHealthResponseApi {
    /** One row per service, worst status first. */
    results: ServiceHealthApi[]
    /** Environments seen in the window. Null stands for spans that set no environment. */
    environments: (string | null)[]
    /**
     * The environment filter the rows were computed for: null for every environment, empty for spans with no environment.
     * @nullable
     */
    environment: string | null
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

export interface ServiceUsageApi {
    /** Log records stored in the window. */
    log_records: number
    /** Uncompressed size of the stored log records in bytes. Billing counts logs by this size. */
    log_bytes: number
    /** Spans of every kind stored in the window. */
    spans: number
    /** Metric data points stored in the window. */
    metric_points: number
    /** Distinct metric series with at least one point in the window. */
    metric_series: number
    /** The service.name resource attribute. */
    service_name: string
}

export interface UsageValuesApi {
    /** Log records stored in the window. */
    log_records: number
    /** Uncompressed size of the stored log records in bytes. Billing counts logs by this size. */
    log_bytes: number
    /** Spans of every kind stored in the window. */
    spans: number
    /** Metric data points stored in the window. */
    metric_points: number
    /** Distinct metric series with at least one point in the window. */
    metric_series: number
}

/**
 * * `logs` - Logs
 * * `traces` - Traces
 * * `metrics` - Metrics
 */
export type UsageSignalEnumApi = (typeof UsageSignalEnumApi)[keyof typeof UsageSignalEnumApi]

export const UsageSignalEnumApi = {
    Logs: 'logs',
    Traces: 'traces',
    Metrics: 'metrics',
} as const

export interface ServiceUsageResponseApi {
    /** One row per service across logs, traces, and metrics, largest logs size first. */
    results: ServiceUsageApi[]
    /** Totals for the whole window, including services past the row limit. */
    totals: UsageValuesApi
    /** Signals that failed to load. Their values are 0 in every row and in the totals. */
    unavailable_signals: UsageSignalEnumApi[]
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

export type ApmDependenciesListParams = {
    /**
     * Start of the window, ISO 8601. Defaults to one hour before date_to.
     */
    date_from?: string
    /**
     * End of the window, ISO 8601. Defaults to now.
     */
    date_to?: string
    /**
     * Environment to list, as resolved from span resource attributes. Omit it for every environment. Pass an empty value for spans that set no environment.
     * @maxLength 200
     */
    environment?: string
    /**
     * Only edges where this service is the caller or the callee.
     * @minLength 1
     * @maxLength 400
     */
    service?: string
}

export type ApmEndpointsListParams = {
    /**
     * Start of the window, ISO 8601. Defaults to one hour before date_to.
     */
    date_from?: string
    /**
     * End of the window, ISO 8601. Defaults to now.
     */
    date_to?: string
    /**
     * Environment to list, as resolved from span resource attributes. Omit it for every environment. Pass an empty value for spans that set no environment.
     * @maxLength 200
     */
    environment?: string
    /**
     * Only list the endpoints of this service.
     * @minLength 1
     * @maxLength 400
     */
    service?: string
}

export type ApmServiceMapListParams = {
    /**
     * Start of the window, ISO 8601. Defaults to one hour before date_to.
     */
    date_from?: string
    /**
     * End of the window, ISO 8601. Defaults to now.
     */
    date_to?: string
    /**
     * Environment to list, as resolved from span resource attributes. Omit it for every environment. Pass an empty value for spans that set no environment.
     * @maxLength 200
     */
    environment?: string
}

export type ApmServicesListParams = {
    /**
     * Start of the window, ISO 8601. Defaults to one hour before date_to.
     */
    date_from?: string
    /**
     * End of the window, ISO 8601. Defaults to now.
     */
    date_to?: string
    /**
     * Environment to list, as resolved from span resource attributes. Omit it for every environment. Pass an empty value for spans that set no environment.
     * @maxLength 200
     */
    environment?: string
}

export type ApmUsageListParams = {
    /**
     * Start of the window, ISO 8601. Defaults to one hour before date_to.
     */
    date_from?: string
    /**
     * End of the window, ISO 8601. Defaults to now.
     */
    date_to?: string
}
