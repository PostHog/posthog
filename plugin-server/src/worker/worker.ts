import * as Sentry from '@sentry/node'
import { exponentialBuckets, Histogram } from 'prom-client'

import { initApp } from '../init'
import { runInTransaction } from '../sentry'
import { Hub, PluginConfig, PluginsServerConfig } from '../types'
import { processError } from '../utils/db/error'
import { status } from '../utils/status'
import { cloneObject, pluginConfigIdFromStack } from '../utils/utils'
import { setupMmdb } from './plugins/mmdb'
import { setupPlugins } from './plugins/setup'
import { workerTasks } from './tasks'
import { TimeoutError } from './vm/vm'

export type PiscinaTaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig, hub: Hub): Promise<PiscinaTaskWorker> {
    initApp(config)

    return runInTransaction(
        {
            name: 'createWorker',
        },
        async () => {
            status.info('🧵', `Starting fake Piscina worker thread`)
            ;['unhandledRejection', 'uncaughtException'].forEach((event) => {
                process.on(event, (error: Error) => {
                    processUnhandledException(error, hub, event)
                })
            })

            const updateJob = await setupMmdb(hub)
            await setupPlugins(hub)

            for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
                if (updateJob) {
                    process.on(signal, updateJob.cancel)
                }
            }

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
                const endTimer = jobDuration.startTimer({
                    task_name: task,
                    task_type: task === 'runPluginJob' ? String(args.job?.type) : '',
                })
                const timer = new Date()
                let response

                Sentry.setContext('task', { task, args })

                if (task in workerTasks) {
                    try {
                        // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
                        response = cloneObject(await workerTasks[task](hub, args))
                    } catch (e) {
                        status.warn('🔔', e)
                        Sentry.captureException(e)
                        throw e
                    }
                } else {
                    response = { error: `Worker task "${task}" not found in: ${Object.keys(workerTasks).join(', ')}` }
                }

                hub.statsd?.timing(`piscina_task.${task}`, timer)
                endTimer()
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
                if (task === 'runEventPipeline') {
                    return transactionDuration > 0.5 ? 1 : 0.01
                } else {
                    return 1
                }
            }
        )

export function processUnhandledException(error: Error, server: Hub, kind: string): void {
    let pluginConfig: PluginConfig | undefined = undefined

    if (error instanceof TimeoutError) {
        pluginConfig = error.pluginConfig
    } else {
        const pluginConfigId = pluginConfigIdFromStack(error.stack || '', server.pluginConfigSecretLookup)
        pluginConfig = pluginConfigId ? server.pluginConfigs.get(pluginConfigId) : undefined
    }

    if (pluginConfig) {
        void processError(server, pluginConfig, error)
        return
    }

    Sentry.captureException(error, {
        extra: {
            type: `${kind} in worker`,
        },
    })

    status.error('🤮', `${kind}!`, { error, stack: error.stack })
}

const jobDuration = new Histogram({
    name: 'piscina_task_duration_seconds',
    help: 'Execution time of piscina tasks, per task name and type',
    labelNames: ['task_name', 'task_type'],
    // We need to cover a pretty wide range, so buckets are set pretty coarse for now
    // and cover 25ms -> 102seconds. We can revisit them later on.
    buckets: exponentialBuckets(0.025, 4, 7),
})
