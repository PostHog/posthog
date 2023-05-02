import Sentry from '@sentry/node'
import { Hub } from 'types'

import { workerTasks } from './tasks'

export const makePiscina = (hub: Hub) => {
    return {
        run: async ({ task, args }: { task: string; args?: any }, _?: any) => {
            try {
                return await workerTasks[task](hub, args)
            } catch (err) {
                Sentry.captureException(err)
                throw err
            }
        },
        broadcastTask: async ({ task, args }: { task: string; args?: any }) => {
            try {
                return [await workerTasks[task](hub, args)]
            } catch (err) {
                Sentry.captureException(err)
                throw err
            }
        },
        on: (_: string, __: any) => null,
    }
}

type Piscina = ReturnType<typeof makePiscina>

export default Piscina
