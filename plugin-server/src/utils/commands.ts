import express from 'express'

import { Hub, PluginServerService } from '../types'
import { reloadPlugins } from '../worker/tasks'
import { populatePluginCapabilities } from '../worker/vm/lazy'
import { parseJSON } from './json-parse'
import { logger } from './logger'
import { PubSub } from './pubsub'

/**
 * We have various use cases where an external service like django needs to communicate with the node services
 *
 * We used to do this via redis pubsub so that all workers could respond. Now we do it slightly differently and have
 * this service to expose an API handler for commands and take care of triggering the pubsub, meaning the other services
 * don't need access to the pubsub redis
 */
export class ServerCommands {
    public readonly messageMap: Record<string, (message: string) => Promise<void>> = {}
    private pubsub: PubSub

    constructor(private hub: Hub) {
        this.messageMap = {
            [this.hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                logger.info('⚡', '[PubSub] Reloading plugins!')
                await reloadPlugins(this.hub)
            },
            'populate-plugin-capabilities': async (message) => {
                const { pluginId } = parseJSON(message) as { pluginId: string }
                logger.info('⚡', '[PubSub] Populating plugin capabilities!', { pluginId })
                if (this.hub?.capabilities.appManagementSingleton) {
                    await populatePluginCapabilities(this.hub, Number(pluginId))
                }
            },
        }

        this.pubsub = new PubSub(this.hub, this.messageMap)
    }

    public get service(): PluginServerService {
        return {
            id: 'server-commands',
            onShutdown: async () => await this.stop(),
            healthcheck: () => true,
        }
    }

    async start() {
        await this.pubsub.start()
    }

    async stop() {
        await this.pubsub.stop()
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

            if (!this.messageMap[command]) {
                res.status(400).json({ error: 'Invalid command' })
                return
            }

            await this.pubsub.publish(command, JSON.stringify(message))

            res.json({ success: true })
        }
}
