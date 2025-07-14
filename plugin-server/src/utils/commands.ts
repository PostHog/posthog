import express from 'express'

import { Hub, PluginServerService } from '../types'
import { reloadPlugins } from '../worker/tasks'
import { populatePluginCapabilities } from '../worker/vm/lazy'
import { logger } from './logger'

/**
 * We have various use cases where an external service like django needs to communicate with the node services
 *
 * We used to do this via redis pubsub so that all workers could respond. Now we do it slightly differently and have
 * this service to expose an API handler for commands and take care of triggering the pubsub, meaning the other services
 * don't need access to the pubsub redis
 */
export class ServerCommands {
    constructor(private hub: Hub) {}

    public get service(): PluginServerService {
        return {
            id: 'server-commands',
            onShutdown: async () => await this.stop(),
            healthcheck: () => true,
        }
    }

    async start(): Promise<void> {
        await this.hub.pubSub.on('reload-plugins', async () => {
            logger.info('⚡', '[PubSub] Reloading plugins!')
            await reloadPlugins(this.hub)
        })

        await this.hub.pubSub.on<{ pluginId: string }>('populate-plugin-capabilities', async ({ pluginId }) => {
            logger.info('⚡', '[PubSub] Populating plugin capabilities!', { pluginId })
            if (this.hub?.capabilities.appManagementSingleton) {
                await populatePluginCapabilities(this.hub, Number(pluginId))
            }
        })
    }

    async stop(): Promise<void> {}

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
