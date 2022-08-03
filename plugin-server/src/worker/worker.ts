import * as Sentry from '@sentry/node'

import { initApp } from '../init'
import { runInTransaction } from '../sentry'
import { Hub, PluginsServerConfig } from '../types'
import { processError } from '../utils/db/error'
import { createHub } from '../utils/db/hub'
import { status } from '../utils/status'
import { cloneObject, pluginConfigIdFromStack } from '../utils/utils'
import { setupPlugins } from './plugins/setup'
import { workerTasks } from './tasks'

export type PiscinaTaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig, threadId: number): Promise<PiscinaTaskWorker> {
    initApp(config)

    return runInTransaction(
        {
            name: 'createWorker',
        },
        async () => {
            status.info('🧵', `Starting Piscina worker thread ${threadId}…`)

            const [hub, closeHub] = await createHub(config, threadId)
            await setupPlugins(hub)

            for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
                process.on(signal, closeHub)
            }

            process.on('unhandledRejection', (error: Error) => processUnhandledRejections(error, hub))

            return createTaskRunner(hub)
        }
    )
}

export const createTaskRunner =
    (hub: Hub): PiscinaTaskWorker =>
    ({ task, args }) =>
        runInTransaction(
            {
                op: 'piscina task',
                name: task,
                data: args,
            },
            async () => {
                const timer = new Date()
                let response

                Sentry.setContext('task', { task, args })

                if (task in workerTasks) {
                    try {
                        // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
                        response = cloneObject(await workerTasks[task](hub, args))
                    } catch (e) {
                        status.info('🔔', e)
                        Sentry.captureException(e)
                        response = { error: e.message }
                    }
                } else {
                    response = { error: `Worker task "${task}" not found in: ${Object.keys(workerTasks).join(', ')}` }
                }

                hub.statsd?.timing(`piscina_task.${task}`, timer)
                if (task === 'runPluginJob') {
                    hub.statsd?.timing('plugin_job', timer, {
                        type: String(args.job?.type),
                        pluginConfigId: String(args.job?.pluginConfigId),
                        pluginConfigTeam: String(args.job?.pluginConfigTeam),
                    })
                }
                return response
            },
            (transactionDuration: number) => {
                if (task === 'runEventPipeline' || task === 'runBufferEventPipeline') {
                    return transactionDuration > 0.2 ? 1 : 0.01
                } else {
                    return 1
                }
            }
        )

export function processUnhandledRejections(error: Error, server: Hub): void {
    const pluginConfigId = pluginConfigIdFromStack(error.stack || '', server.pluginConfigSecretLookup)
    const pluginConfig = pluginConfigId ? server.pluginConfigs.get(pluginConfigId) : null

    if (pluginConfig) {
        void processError(server, pluginConfig, error)
        return
    }

    Sentry.captureException(error, {
        extra: {
            type: 'Unhandled promise error in worker',
        },
    })

    status.error('🤮', `Unhandled Promise Error!`)
    status.error('🤮', error)
}
