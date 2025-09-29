import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, Hub, PluginServerService } from '../../types'
import { LinksService } from '../services/links/links.service'

export class LinksApi {
    private linksService: LinksService

    constructor(private hub: Hub) {
        this.linksService = new LinksService(hub)
    }

    public get service(): PluginServerService {
        return {
            id: 'links-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? new HealthCheckResultError('Links API is not healthy', {}),
        }
    }

    async start(): Promise<void> {
        // await this.
    }

    async stop(): Promise<void> {
        await this.linksService.stop()
    }

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

        router.get('/public/links/:id', asyncHandler(this.handleLink()))

        return router
    }

    private handleLink =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                await this.linksService.processLink(req, res)
            } catch (error) {
                return res.status(500).json({ error: 'Internal error' })
            }
        }
}
