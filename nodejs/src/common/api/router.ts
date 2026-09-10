import * as prometheus from 'prom-client'
import express, { NextFunction, Request, Response } from 'ultimate-express'

import { corsMiddleware } from '~/common/api/middleware/cors'
import { httpMetricsMiddleware } from '~/common/api/middleware/http-metrics'
import { createInternalApiAuthMiddleware } from '~/common/api/middleware/internal-api-auth'
import { logger } from '~/common/utils/logger'
import { HealthCheckResultError, PluginServerService } from '~/types'

prometheus.collectDefaultMetrics()

export function initializePrometheusLabels(
    ingestionPipeline: string | null = null,
    ingestionLane: string | null = null
): void {
    const labels: Record<string, string> = {}
    if (ingestionPipeline) {
        labels['ingestion_pipeline'] = ingestionPipeline
    }
    if (ingestionLane) {
        labels['ingestion_lane'] = ingestionLane
    }
    if (Object.keys(labels).length > 0) {
        prometheus.register.setDefaultLabels(labels)
    }
}

export interface SetupExpressAppOptions {
    // Path prefixes exempt from the shared-secret middleware. Used by servers that own auth on those
    // paths themselves, such as recording-api verifying a team-scoped JWT across the whole prefix.
    internalApiAuthExcludedPathPrefixes?: string[]
    internalApiSecret?: string
    // Comma-separated previous secrets still accepted for verification during rotation.
    internalApiSecretFallbacks?: string
    // JSON body size limit, e.g. '20mb'. Overridable in tests.
    jsonBodyLimit?: string
}

export function setupCommonRoutes(
    app: express.Application,
    services: Pick<PluginServerService, 'id' | 'healthcheck'>[]
): express.Application {
    app.get('/_health', buildGetHealth(services))
    app.get('/_ready', buildGetHealth(services))
    app.get('/_metrics', getMetrics)
    app.get('/metrics', getMetrics)

    return app
}

export function setupExpressApp(options: SetupExpressAppOptions = {}): express.Application {
    const app = express()

    // Add CORS middleware before other middleware
    app.use(corsMiddleware)

    // Track HTTP request duration and status codes per route pattern
    app.use(httpMetricsMiddleware)

    // Add internal API authentication middleware for defense-in-depth.
    // Primary protection comes from Contour routing at the infra level.
    app.use(
        createInternalApiAuthMiddleware({
            secret: options.internalApiSecret || '',
            fallbacks: (options.internalApiSecretFallbacks || '')
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            excludedPathPrefixes: options.internalApiAuthExcludedPathPrefixes,
        })
    )

    app.use(
        express.json({
            limit: options.jsonBodyLimit ?? '20mb',
            verify: (req, res, buf) => {
                ;(req as any).rawBody = buf.toString('utf8')
            },
        })
    )

    // ultimate-express reports an oversized body as a plain Error with no
    // status, which the default handler renders as a 500 — indistinguishable
    // from a worker crash for callers deciding whether to retry. Answer 413 so
    // clients (the Rust ingestion consumer) split the payload instead of
    // retrying it verbatim. Also match express-style body-parser errors
    // (status 413 / type entity.too.large) for compatibility.
    app.use((err: any, _req: Request, res: Response, next: NextFunction) => {
        if (err?.message === 'Request entity too large' || err?.status === 413 || err?.type === 'entity.too.large') {
            res.status(413).json({ status: 'error', error: 'Request entity too large' })
            return
        }
        next(err)
    })

    return app
}

export type ModifiedRequest = Request & { rawBody?: string }

const buildGetHealth =
    (services: Pick<PluginServerService, 'id' | 'healthcheck'>[]) => async (req: Request, res: Response) => {
        // Check that all health checks pass. Note that a failure of these
        // _may_ result in the process being terminated by e.g. Kubernetes
        // so the stakes are high.
        //
        // Also, Kubernetes will call this endpoint frequently, on each pod,
        // so we want to make sure it's fast and doesn't put any stress on
        // other services. Ideally it shouldn't make any calls to other
        // services.
        //
        // Here we take all of the health checks we are given, run them in
        // parallel, and return the results. If any of the checks fail, we
        // return a 503 status code, otherwise we return a 200 status code.
        //
        // In all cases we should return a JSON object with the following
        // structure:
        //
        // {
        //   "status": "ok" | "error",
        //   "checks": {
        //     "service1": "ok" | "error",
        //     "service2": "ok" | "error",
        //     ...
        //   }
        // }
        const healthCheckPromises = services.map(async (service) => {
            try {
                const result = await service.healthcheck()
                return { service, result }
            } catch (error) {
                // If healthcheck throws, create an error result
                return {
                    service,
                    result: new HealthCheckResultError(error instanceof Error ? error.message : 'Unknown error', {}),
                }
            }
        })

        const healthChecks = await Promise.all(healthCheckPromises)

        // Convert to response format for API
        const checkResults = healthChecks.map(({ service, result }) => result.toResponse(service.id))

        // Use isError() method to determine status code
        const statusCode = healthChecks.every(({ result }) => !result.isError()) ? 200 : 503

        const checkResultsMapping = Object.fromEntries(
            checkResults.map((result) => [
                result.service,
                result.message ? { status: result.status, message: result.message } : result.status,
            ])
        )

        if (statusCode === 200) {
            logger.debug('💚', 'Server liveness check succeeded')
        } else {
            const failedServices = checkResults.filter((r) => r.status === 'error')
            logger.error('💔', 'Server liveness check failed', {
                failedServices: failedServices.map((s) => ({
                    service: s.service,
                    message: s.message,
                    details: 'details' in s ? s.details : undefined,
                })),
            })
        }

        return res.status(statusCode).json({ status: statusCode === 200 ? 'ok' : 'error', checks: checkResultsMapping })
    }

const getMetrics = async (req: Request, res: Response) => {
    try {
        const metrics = await prometheus.register.metrics()
        res.send(metrics)
    } catch (err) {
        logger.error('🩺', 'Error while collecting metrics', { err })
        res.sendStatus(500)
    }
}
