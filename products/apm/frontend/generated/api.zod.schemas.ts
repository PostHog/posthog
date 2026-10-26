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

export const ServiceHealthStatusEnumApi = zod
    .enum(['good', 'warning', 'serious', 'critical'])
    .describe('\* `good` - good\n\* `warning` - warning\n\* `serious` - serious\n\* `critical` - critical')

export type ServiceHealthStatusEnumApi = zod.input<typeof ServiceHealthStatusEnumApi>
export type ServiceHealthStatusEnumApiOutput = zod.output<typeof ServiceHealthStatusEnumApi>

export const HealthRowApi = zod.object({
    request_rate: zod.number().nullable().describe('Requests per second over the window.'),
    error_rate: zod.number().nullable().describe('Share of requests with an error status, 0 to 1.'),
    p95_ms: zod.number().nullable().describe('95th percentile request duration in milliseconds.'),
    span_count: zod.number().describe('Requests counted in the window.'),
    error_count: zod.number().describe('Requests with an error status in the window.'),
})

export type HealthRowApi = zod.input<typeof HealthRowApi>
export type HealthRowApiOutput = zod.output<typeof HealthRowApi>

export const ServiceHealthApi = zod.object({
    service_name: zod.string().describe('The service.name resource attribute.'),
    environment: zod.string().describe('The environment the row was computed for.'),
    status: zod
        .enum(['good', 'warning', 'serious', 'critical'])
        .describe('\* `good` - good\n\* `warning` - warning\n\* `serious` - serious\n\* `critical` - critical')
        .describe(
            'Health band from the error rate.\n\n\* `good` - good\n\* `warning` - warning\n\* `serious` - serious\n\* `critical` - critical'
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
                        '\* `good` - good\n\* `warning` - warning\n\* `serious` - serious\n\* `critical` - critical'
                    )
                    .describe(
                        'Health band from the error rate.\n\n\* `good` - good\n\* `warning` - warning\n\* `serious` - serious\n\* `critical` - critical'
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
