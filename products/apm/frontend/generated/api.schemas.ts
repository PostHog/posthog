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
}

export interface EndpointHealthApi {
    /** The service.name resource attribute. */
    service_name: string
    /** The entry span name, for example the HTTP route or the job name. */
    endpoint: string
    /** The environment the row was computed for. */
    environment: string
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
    /** The environment the rows were computed for. */
    environment: string
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
    /** The environment the map was built for. */
    environment: string
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
}

export interface ServiceHealthApi {
    /** The service.name resource attribute. */
    service_name: string
    /** The environment the row was computed for. */
    environment: string
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
    /** Environments seen in the window. */
    environments: string[]
    /** The environment the rows were computed for. */
    environment: string
    /** Start of the window used. */
    date_from: string
    /** End of the window used. */
    date_to: string
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
     * Environment to list, as resolved from span resource attributes. Defaults to 'default'.
     * @minLength 1
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
     * Environment to list, as resolved from span resource attributes. Defaults to 'default'.
     * @minLength 1
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
     * Environment to list, as resolved from span resource attributes. Defaults to 'default'.
     * @minLength 1
     * @maxLength 200
     */
    environment?: string
}
