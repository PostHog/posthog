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
    endpoint: zod.string().describe('The entry span name, for example the HTTP route or the job name.'),
    environment: zod.string().describe('The environment the row was computed for.'),
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
                endpoint: zod.string().describe('The entry span name, for example the HTTP route or the job name.'),
                environment: zod.string().describe('The environment the row was computed for.'),
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
    environment: zod.string().describe('The environment the rows were computed for.'),
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
    environment: zod.string().describe('The environment the map was built for.'),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type ServiceMapResponseApi = zod.input<typeof ServiceMapResponseApi>
export type ServiceMapResponseApiOutput = zod.output<typeof ServiceMapResponseApi>

export const ServiceHealthApi = zod.object({
    service_name: zod.string().describe('The service.name resource attribute.'),
    environment: zod.string().describe('The environment the row was computed for.'),
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
                environment: zod.string().describe('The environment the row was computed for.'),
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
    environments: zod.array(zod.string()).describe('Environments seen in the window.'),
    environment: zod.string().describe('The environment the rows were computed for.'),
    date_from: zod.iso.datetime({ offset: true }).describe('Start of the window used.'),
    date_to: zod.iso.datetime({ offset: true }).describe('End of the window used.'),
})

export type ServicesHealthResponseApi = zod.input<typeof ServicesHealthResponseApi>
export type ServicesHealthResponseApiOutput = zod.output<typeof ServicesHealthResponseApi>
