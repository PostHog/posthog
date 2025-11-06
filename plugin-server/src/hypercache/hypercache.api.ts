import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, Hub, PluginServerService } from '../types'
import { HypercacheService } from './services/hypercache.service'

export class HypercacheApi {
    private hypercache: HypercacheService

    constructor(private hub: Hub) {
        this.hypercache = new HypercacheService(hub)
    }

    public get service(): PluginServerService {
        return {
            id: 'hypercache-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? new HealthCheckResultError('Hypercache API is not healthy', {}),
        }
    }

    async start(): Promise<void> {}
    async stop(): Promise<void> {}

    isHealthy(): HealthCheckResult {
        // NOTE: There isn't really anything to check for here so we are just always healthy
        return new HealthCheckResultOk()
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: ModifiedRequest, res: express.Response) => Promise<void>) =>
            (req: ModifiedRequest, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        router.get('/public/hypercache/api/surveys', asyncHandler(this.getSurveys()))

        return router
    }

    private getSurveys =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const response = await this.hypercache.getResourceViaToken('surveys.json', req.query.token)

            if (response.cacheResult === 'hit') {
                res.set('X-PostHog-Cache-Source', response.cacheSource === 'redis' ? '0' : '1')
                res.set('Content-Type', 'application/json').send(response.data)
            } else {
                res.status(404).json({
                    type: 'authentication_error',
                    code: 'invalid_api_key',
                    detail: 'Project API key invalid. You can find your project API key in your PostHog project settings.',
                    attr: null,
                })
            }
        }
}
