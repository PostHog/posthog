import * as prometheus from 'prom-client'
import express, { Request, Response } from 'ultimate-express'

import { corsMiddleware } from '~/api/middleware/cors'
import { PluginServerService } from '~/types'
import { logger } from '~/utils/logger'

prometheus.collectDefaultMetrics()

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

export function setupExpressApp(): express.Application {
    const app = express()

    // Add CORS middleware before other middleware
    app.use(corsMiddleware)

    app.use(
        express.json({
            limit: '200kb',
            verify: (req, res, buf) => {
                ;(req as any).rawBody = buf.toString('utf8')
            },
        })
    )

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
        const checkResults = await Promise.all(
            // Note that we do not use `Promise.allSettled` here so we can
            // assume that all promises have resolved. If there was a
            // rejected promise, the http server should catch it and return
            // a 500 status code.
            services.map(async (service) => {
                try {
                    return { service: service.id, status: (await service.healthcheck()) ? 'ok' : 'error' }
                } catch (error) {
                    return { service: service.id, status: 'error', error: error.message }
                }
            })
        )

        const statusCode = checkResults.every((result) => result.status === 'ok') ? 200 : 503

        const checkResultsMapping = Object.fromEntries(checkResults.map((result) => [result.service, result.status]))

        if (statusCode === 200) {
            logger.info('💚', 'Server liveness check succeeded')
        } else {
            logger.error('💔', 'Server liveness check failed', { checkResults: checkResultsMapping })
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
