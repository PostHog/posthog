import express from 'ultimate-express'

import { Hub, PluginServerService } from '../types'

export class FlagsApi {
    constructor(private hub: Hub) {}

    public get service(): PluginServerService {
        return {
            id: 'flags-api',
            onShutdown: async () => {},
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    isHealthy() {
        // NOTE: There isn't really anything to check for here so we are just always healthy
        return true
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: express.Request, res: express.Response) => Promise<void>) =>
            (req: express.Request, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        router.get('/public/flags/local_evaluation', asyncHandler(this.getLocalEvaluation()))

        return router
    }

    private getLocalEvaluation =
        () =>
        async (req: express.Request, res: express.Response): Promise<any> => {
            console.log(req.body)

            return res.set('Allow', 'POST').status(405).json({
                error: 'Method not allowed',
            })
        }
}
