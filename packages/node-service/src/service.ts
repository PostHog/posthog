import { trace } from '@opentelemetry/api'
import { Hono } from 'hono'
import type { Logger } from 'pino'

import { createLogger, serializeError, type LogLevel } from './logging.js'
import { createServiceMetrics, type ServiceMetrics } from './metrics.js'
import { createTracingMiddleware } from './tracing.js'
import type { HealthCheck, HealthCheckResult, ServiceBindings, ServiceState } from './types.js'

const PROBE_PATHS = new Set(['/_health', '/_ready', '/_metrics'])

interface HonoVariables {
    requestId: string
}

export interface CreateNodeServiceOptions {
    name: string
    logLevel?: LogLevel
    logger?: Logger
    metrics?: ServiceMetrics
    readinessChecks?: Record<string, HealthCheck>
    tracing?: boolean
}

export interface NodeService extends ServiceBindings {
    app: Hono<{ Variables: HonoVariables }>
    name: string
}

function requestIdFromHeader(headerValue: string | undefined): string {
    if (headerValue && /^[A-Za-z0-9._:-]{1,128}$/.test(headerValue)) {
        return headerValue
    }
    return crypto.randomUUID()
}

async function runReadinessChecks(
    checks: Record<string, HealthCheck>,
    logger: Logger
): Promise<Record<string, HealthCheckResult>> {
    const entries = await Promise.all(
        Object.entries(checks).map(async ([name, check]) => {
            try {
                return [name, await check()] as const
            } catch (error) {
                logger.error(
                    { event: 'service.readiness_check_failed', check: name, error: serializeError(error) },
                    'Readiness check failed'
                )
                return [name, { status: 'error' }] as const
            }
        })
    )
    return Object.fromEntries(entries)
}

export function createNodeService(options: CreateNodeServiceOptions): NodeService {
    const logger =
        options.logger ??
        createLogger({
            serviceName: options.name,
            ...(options.logLevel ? { level: options.logLevel } : {}),
        })
    const metrics = options.metrics ?? createServiceMetrics(options.name)
    const state: ServiceState = { ready: false, shuttingDown: false }
    const app = new Hono<{ Variables: HonoVariables }>()

    app.onError((error, context) => {
        logger.error(
            {
                event: 'http.unhandled_error',
                request_id: context.get('requestId'),
                method: context.req.method,
                route: context.req.routePath || 'unmatched',
                error: serializeError(error),
            },
            'Unhandled HTTP error'
        )
        return context.json({ error: 'Internal server error' }, 500)
    })

    app.use('*', async (context, next) => {
        const requestId = requestIdFromHeader(context.req.header('x-request-id'))
        context.set('requestId', requestId)
        context.header('X-Request-ID', requestId)
        await next()
    })

    app.use('*', async (context, next) => {
        await next()
        context.header('X-Content-Type-Options', 'nosniff')
        context.header('X-Frame-Options', 'DENY')
    })

    if (options.tracing !== false) {
        app.use('*', createTracingMiddleware(options.name))
    }

    app.use('*', async (context, next) => {
        const pathname = new URL(context.req.url).pathname
        if (pathname === '/_metrics') {
            await next()
            return
        }

        const method = context.req.method
        metrics.httpRequestsActive.inc({ method })
        const startedAt = performance.now()

        try {
            await next()
        } finally {
            const route = context.req.routePath || 'unmatched'
            const statusCode = String(context.res.status)
            metrics.httpRequestsActive.dec({ method })
            metrics.httpRequestsTotal.inc({ method, route, status_code: statusCode })
            metrics.httpRequestDurationSeconds.observe(
                { method, route, status_code: statusCode },
                (performance.now() - startedAt) / 1000
            )
        }
    })

    app.use('*', async (context, next) => {
        const pathname = new URL(context.req.url).pathname
        if (PROBE_PATHS.has(pathname)) {
            await next()
            return
        }

        const startedAt = performance.now()
        try {
            await next()
        } finally {
            const spanContext = trace.getActiveSpan()?.spanContext()
            logger.info(
                {
                    event: 'http.request',
                    request_id: context.get('requestId'),
                    trace_id: spanContext?.traceId,
                    method: context.req.method,
                    route: context.req.routePath || 'unmatched',
                    status_code: context.res.status,
                    duration_ms: Math.round((performance.now() - startedAt) * 100) / 100,
                },
                'HTTP request completed'
            )
        }
    })

    app.get('/_health', (context) => context.json({ status: 'ok' }))

    app.get('/_ready', async (context) => {
        const checks = await runReadinessChecks(options.readinessChecks ?? {}, logger)
        const checksReady = Object.values(checks).every((check) => check.status === 'ok')
        const ready = state.ready && !state.shuttingDown && checksReady
        return context.json({ status: ready ? 'ok' : 'error', checks }, ready ? 200 : 503)
    })

    app.get('/_metrics', async (context) => {
        context.header('Content-Type', metrics.registry.contentType)
        return context.body(await metrics.registry.metrics())
    })

    return { app, logger, metrics, name: options.name, state }
}
