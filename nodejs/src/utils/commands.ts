import express from 'ultimate-express'

import { HealthCheckResultOk, Hub, PluginServerService } from '../types'

/** Narrowed Hub type for ServerCommands */
export type ServerCommandsHub = Pick<Hub, 'pubSub'>

/**
 * We have various use cases where an external service like django needs to communicate with the node services
 *
 * We used to do this via redis pubsub so that all workers could respond. Now we do it slightly differently and have
 * this service to expose an API handler for commands and take care of triggering the pubsub, meaning the other services
 * don't need access to the pubsub redis
 */
export class ServerCommands {
    constructor(private hub: ServerCommandsHub) {}

    public get service(): PluginServerService {
        return {
            id: 'server-commands',
            onShutdown: async () => {},
            healthcheck: () => new HealthCheckResultOk(),
        }
    }

    public router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: express.Request, res: express.Response) => Promise<void>) =>
            (req: express.Request, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        router.post('/api/commands', asyncHandler(this.postCommand()))

        return router
    }

    private postCommand =
        () =>
        async (req: express.Request, res: express.Response): Promise<void> => {
            const { command, message } = req.body

            await this.hub.pubSub.publish(command, JSON.stringify(message))

            res.json({ success: true })
        }
}
