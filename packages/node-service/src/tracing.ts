import { SpanStatusCode, trace } from '@opentelemetry/api'
import type { MiddlewareHandler } from 'hono'

export function createTracingMiddleware(serviceName: string): MiddlewareHandler {
    const tracer = trace.getTracer(serviceName)

    return async (context, next) => {
        const method = context.req.method
        const pathname = new URL(context.req.url).pathname

        await tracer.startActiveSpan(`${method} HTTP request`, async (span) => {
            span.setAttribute('http.request.method', method)
            span.setAttribute('url.path', pathname)

            try {
                await next()
                const route = context.req.routePath || 'unmatched'
                span.updateName(`${method} ${route}`)
                span.setAttribute('http.response.status_code', context.res.status)
                span.setAttribute('http.route', route)
                if (context.res.status >= 500) {
                    span.setStatus({ code: SpanStatusCode.ERROR })
                }
            } catch (error) {
                span.recordException(error instanceof Error ? error : new Error(String(error)))
                span.setStatus({ code: SpanStatusCode.ERROR })
                throw error
            } finally {
                span.end()
            }
        })
    }
}
