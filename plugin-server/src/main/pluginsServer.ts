import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../config/config'
import { Hub, JobQueueConsumerControl, PluginsServerConfig, Queue, ScheduleControl } from '../types'
import { createHub } from '../utils/db/hub'
import { killProcess } from '../utils/kill'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { statusReport } from '../utils/status-report'
import { delay, getPiscinaStats } from '../utils/utils'
import { startQueues } from './ingestion-queues/queue'
import { startJobQueueConsumer } from './job-queues/job-queue-consumer'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'
import { startSchedule } from './services/schedule'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    piscina: Piscina
    queue: Queue
    mmdb?: ReaderModel
    mmdbUpdateJob?: schedule.Job
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (config: PluginsServerConfig) => Piscina
): Promise<ServerInstance> {
    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)

    let pubSub: PubSub | undefined
    let hub: Hub | undefined
    let actionsReloadJob: schedule.Job | undefined
    let pingJob: schedule.Job | undefined
    let piscinaStatsJob: schedule.Job | undefined
    let internalMetricsStatsJob: schedule.Job | undefined
    let pluginMetricsJob: schedule.Job | undefined
    let piscina: Piscina | undefined
    let queue: Queue | undefined // ingestion queue
    let redisQueueForPluginJobs: Queue | undefined | null
    let jobQueueConsumer: JobQueueConsumerControl | undefined
    let closeHub: () => Promise<void> | undefined
    let scheduleControl: ScheduleControl | undefined
    let mmdbServer: net.Server | undefined
    let lastActivityCheck: NodeJS.Timeout | undefined

    let shutdownStatus = 0

    async function closeJobs(): Promise<void> {
        shutdownStatus += 1
        if (shutdownStatus === 2) {
            status.info('🔁', 'Try again to shut down forcibly')
            return
        }
        if (shutdownStatus >= 3) {
            status.info('❗️', 'Shutting down forcibly!')
            void piscina?.destroy()
            process.exit()
        }
        status.info('💤', ' Shutting down gracefully...')
        lastActivityCheck && clearInterval(lastActivityCheck)
        await queue?.stop()
        await redisQueueForPluginJobs?.stop()
        await pubSub?.stop()
        actionsReloadJob && schedule.cancelJob(actionsReloadJob)
        pingJob && schedule.cancelJob(pingJob)
        pluginMetricsJob && schedule.cancelJob(pluginMetricsJob)
        statusReport.stopStatusReportSchedule()
        piscinaStatsJob && schedule.cancelJob(piscinaStatsJob)
        internalMetricsStatsJob && schedule.cancelJob(internalMetricsStatsJob)
        await jobQueueConsumer?.stop()
        await scheduleControl?.stopSchedule()
        await new Promise<void>((resolve, reject) =>
            !mmdbServer
                ? resolve()
                : mmdbServer.close((error) => {
                      if (error) {
                          reject(error)
                      } else {
                          status.info('🛑', 'Closed internal MMDB server!')
                          resolve()
                      }
                  })
        )
        if (piscina) {
            await stopPiscina(piscina)
        }
        await closeHub?.()
        status.info('👋', 'Over and out!')
        // wait an extra second for any misc async task to finish
        await delay(1000)
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        await closeJobs()
        process.exit(0)
    })

    try {
        ;[hub, closeHub] = await createHub(serverConfig, null)

        const serverInstance: Partial<ServerInstance> & Pick<ServerInstance, 'hub'> = {
            hub,
        }

        if (!serverConfig.DISABLE_MMDB) {
            serverInstance.mmdb = (await prepareMmdb(serverInstance)) ?? undefined
            serverInstance.mmdbUpdateJob = schedule.scheduleJob(
                '0 */4 * * *',
                async () => await performMmdbStalenessCheck(serverInstance)
            )
            mmdbServer = await createMmdbServer(serverInstance)
            serverConfig.INTERNAL_MMDB_SERVER_PORT = (mmdbServer.address() as AddressInfo).port
            hub.INTERNAL_MMDB_SERVER_PORT = serverConfig.INTERNAL_MMDB_SERVER_PORT
        }

        piscina = makePiscina(serverConfig)

        scheduleControl = await startSchedule(hub, piscina)
        jobQueueConsumer = await startJobQueueConsumer(hub, piscina)

        const queues = await startQueues(hub, piscina)

        // `queue` refers to the ingestion queue. With Celery ingestion, we only
        // have one queue for plugin jobs and ingestion. With Kafka ingestion, we
        // use Kafka for events but still start Redis for plugin jobs.
        // Thus, if Kafka is disabled, we don't need to call anything on
        // redisQueueForPluginJobs, as that will also be the ingestion queue.
        queue = queues.ingestion
        redisQueueForPluginJobs = config.KAFKA_ENABLED ? queues.auxiliary : null
        piscina.on('drain', () => {
            void queue?.resume()
            void redisQueueForPluginJobs?.resume()

            void jobQueueConsumer?.resume()
        })

        // use one extra Redis connection for pub-sub
        pubSub = new PubSub(hub, {
            [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                status.info('⚡', 'Reloading plugins!')
                await piscina?.broadcastTask({ task: 'reloadPlugins' })
                await scheduleControl?.reloadSchedule()
            },
            'reload-action': async (message) =>
                await piscina?.broadcastTask({ task: 'reloadAction', args: JSON.parse(message) }),
            'drop-action': async (message) =>
                await piscina?.broadcastTask({ task: 'dropAction', args: JSON.parse(message) }),
        })
        await pubSub.start()

        if (hub.jobQueueManager) {
            const queueString = hub.jobQueueManager.getJobQueueTypesAsString()
            await hub!.db!.redisSet('@posthog-plugin-server/enabled-job-queues', queueString)
        }

        // every 5 minutes all ActionManager caches are reloaded for eventual consistency
        actionsReloadJob = schedule.scheduleJob('*/5 * * * *', async () => {
            await piscina?.broadcastTask({ task: 'reloadAllActions' })
        })
        // every 5 seconds set Redis keys @posthog-plugin-server/ping and @posthog-plugin-server/version
        pingJob = schedule.scheduleJob('*/5 * * * * *', async () => {
            await hub!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, {
                jsonSerialize: false,
            })
            await hub!.db!.redisSet('@posthog-plugin-server/version', version, undefined, { jsonSerialize: false })
        })
        // every 10 seconds sends stuff to StatsD
        piscinaStatsJob = schedule.scheduleJob('*/10 * * * * *', () => {
            if (piscina) {
                for (const [key, value] of Object.entries(getPiscinaStats(piscina))) {
                    hub!.statsd?.gauge(`piscina.${key}`, value)
                }
            }
        })

        // every minute flush internal metrics
        if (hub.internalMetrics) {
            internalMetricsStatsJob = schedule.scheduleJob('0 * * * * *', async () => {
                await hub!.internalMetrics?.flush(piscina!)
            })
        }

        pluginMetricsJob = schedule.scheduleJob('*/30 * * * *', async () => {
            await piscina!.broadcastTask({ task: 'sendPluginMetrics' })
        })

        if (serverConfig.STALENESS_RESTART_SECONDS > 0) {
            // check every 10 sec how long it has been since the last activity
            let lastFoundActivity: number
            lastActivityCheck = setInterval(() => {
                if (
                    hub?.lastActivity &&
                    new Date().valueOf() - hub?.lastActivity > serverConfig.STALENESS_RESTART_SECONDS * 1000 &&
                    lastFoundActivity !== hub?.lastActivity
                ) {
                    lastFoundActivity = hub?.lastActivity
                    const extra = {
                        instanceId: hub.instanceId.toString(),
                        lastActivity: hub.lastActivity ? new Date(hub.lastActivity).toISOString() : null,
                        lastActivityType: hub.lastActivityType,
                        piscina: piscina ? JSON.stringify(getPiscinaStats(piscina)) : null,
                    }
                    Sentry.captureMessage(
                        `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                        {
                            extra,
                        }
                    )
                    console.log(
                        `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                        extra
                    )
                    hub.statsd?.increment(`alerts.stale_plugin_server_restarted`)

                    killProcess()
                }
            }, Math.min(serverConfig.STALENESS_RESTART_SECONDS, 10000))
        }

        serverInstance.piscina = piscina
        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        status.info('🚀', 'All systems go')

        hub.lastActivity = new Date().valueOf()
        hub.lastActivityType = 'serverStart'

        return serverInstance as ServerInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', error)
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        await closeJobs()
        process.exit(1)
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait *up to* 5 seconds to shut down VMs.
    await Promise.race([piscina.broadcastTask({ task: 'teardownPlugins' }), delay(5000)])
    // Wait 2 seconds to flush the last queues.
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
    await piscina.destroy()
}
