import { Hub, PluginsServerConfig } from '~/src/types'

import { captureException } from '../utils/posthog'
import { createWorker } from './worker'

export const makePiscina = async (serverConfig: PluginsServerConfig, hub: Hub) => {
    const worker = await createWorker(serverConfig, hub)
    return {
        run: async ({ task, args }: { task: string; args?: any }) => {
            try {
                return await worker({ task, args: args ?? undefined })
            } catch (err) {
                captureException(err)
                throw err
            }
        },
        broadcastTask: async ({ task, args }: { task: string; args?: any }) => {
            try {
                return [await worker({ task, args: args ?? undefined })]
            } catch (err) {
                captureException(err)
                throw err
            }
        },
        on: (_: string, __: any) => null,
    }
}

type Piscina = Awaited<ReturnType<typeof makePiscina>>

export default Piscina
