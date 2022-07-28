import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { Server } from 'http'
import { Consumer, KafkaJSProtocolError } from 'kafkajs'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../config/config'
import { KAFKA_HEALTHCHECK } from '../config/kafka-topics'
import {
    Hub,
    JobQueueConsumerControl,
    PluginScheduleControl,
    PluginServerCapabilities,
    PluginsServerConfig,
} from '../types'
import { createHub } from '../utils/db/hub'
import { killProcess } from '../utils/kill'
import { captureEventLoopMetrics } from '../utils/metrics'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { delay, getPiscinaStats, stalenessCheck } from '../utils/utils'
import { KafkaQueue } from './ingestion-queues/kafka-queue'
import { startQueues } from './ingestion-queues/queue'
import { startJobQueueConsumer } from './job-queues/job-queue-consumer'
import { createHttpServer } from './services/http-server'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'
import { startPluginSchedules } from './services/schedule'
import { setupKafkaHealthcheckConsumer } from './utils'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    piscina: Piscina
    queue: KafkaQueue | null
    mmdb?: ReaderModel
    kafkaHealthcheckConsumer?: Consumer
    mmdbUpdateJob?: schedule.Job
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (config: PluginsServerConfig) => Piscina,
    capabilities: PluginServerCapabilities | null = null
): Promise<ServerInstance> {
    const timer = new Date()

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)

    let pubSub: PubSub | undefined
    let hub: Hub | undefined
    let piscina: Piscina | undefined
    let queue: KafkaQueue | undefined | null // ingestion queue
    let healthCheckConsumer: Consumer | undefined
    let jobQueueConsumer: JobQueueConsumerControl | undefined
    let closeHub: () => Promise<void> | undefined
    let pluginScheduleControl: PluginScheduleControl | undefined
    let mmdbServer: net.Server | undefined
    let lastActivityCheck: NodeJS.Timeout | undefined
    let httpServer: Server | undefined
    let stopEventLoopMetrics: (() => void) | undefined

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
        cancelAllScheduledJobs()
        stopEventLoopMetrics?.()
        await queue?.stop()
        await pubSub?.stop()
        await jobQueueConsumer?.stop()
        await pluginScheduleControl?.stopSchedule()
        await healthCheckConsumer?.stop()
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
        httpServer?.close()

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

    process.on('unhandledRejection', (error: Error) => {
        status.error('🤮', 'Unhandled Promise Rejection!')
        status.error('🤮', error)

        // Don't send some Kafka normal operation "errors" to Sentry - kafkajs handles these correctly
        if (error instanceof KafkaJSProtocolError) {
            if (error.message.includes('The group is rebalancing, so a rejoin is needed')) {
                hub!.statsd?.increment(`kafka_consumer_group_rebalancing`)
                return
            }

            if (error.message.includes('Specified group generation id is not valid')) {
                hub!.statsd?.increment(`kafka_consumer_invalid_group_generation_id`)
                return
            }
        }

        Sentry.captureException(error)
    })

    try {
        ;[hub, closeHub] = await createHub(serverConfig, null, capabilities)

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

        if (hub.capabilities.pluginScheduledTasks) {
            pluginScheduleControl = await startPluginSchedules(hub, piscina)
        }
        if (hub.capabilities.ingestion || hub.capabilities.processPluginJobs) {
            jobQueueConsumer = await startJobQueueConsumer(hub, piscina)
        }

        const queues = await startQueues(hub, piscina)

        // `queue` refers to the ingestion queue.
        queue = queues.ingestion
        piscina.on('drain', () => {
            void jobQueueConsumer?.resume()
        })

        // use one extra Redis connection for pub-sub
        pubSub = new PubSub(hub, {
            [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                status.info('⚡', 'Reloading plugins!')
                await piscina?.broadcastTask({ task: 'reloadPlugins' })
                await pluginScheduleControl?.reloadSchedule()
            },
            ...(hub.capabilities.processAsyncHandlers
                ? {
                      'reload-action': async (message) =>
                          await piscina?.broadcastTask({ task: 'reloadAction', args: JSON.parse(message) }),
                      'drop-action': async (message) =>
                          await piscina?.broadcastTask({ task: 'dropAction', args: JSON.parse(message) }),
                  }
                : {}),
        })

        await pubSub.start()

        if (hub.jobQueueManager) {
            const queueString = hub.jobQueueManager.getJobQueueTypesAsString()
            await hub!.db!.redisSet('@posthog-plugin-server/enabled-job-queues', queueString)
        }

        // every 5 minutes all ActionManager caches are reloaded for eventual consistency
        schedule.scheduleJob('*/5 * * * *', async () => {
            await piscina?.broadcastTask({ task: 'reloadAllActions' })
        })
        // every 5 seconds set Redis keys @posthog-plugin-server/ping and @posthog-plugin-server/version
        schedule.scheduleJob('*/5 * * * * *', async () => {
            await hub!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, {
                jsonSerialize: false,
            })
            await hub!.db!.redisSet('@posthog-plugin-server/version', version, undefined, { jsonSerialize: false })
        })
        // every 10 seconds sends stuff to StatsD
        schedule.scheduleJob('*/10 * * * * *', () => {
            if (piscina) {
                for (const [key, value] of Object.entries(getPiscinaStats(piscina))) {
                    if (value !== undefined) {
                        hub!.statsd?.gauge(`piscina.${key}`, value)
                    }
                }
            }
        })

        // every minute log information on kafka consumer
        if (queue) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await queue?.emitConsumerGroupMetrics()
            })
        }

        // every minute flush internal metrics
        if (hub.internalMetrics) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await hub!.internalMetrics?.flush(piscina!)
            })
        }

        if (hub.statsd) {
            stopEventLoopMetrics = captureEventLoopMetrics(hub.statsd, hub.instanceId)
        }

        if (serverConfig.STALENESS_RESTART_SECONDS > 0) {
            // check every 10 sec how long it has been since the last activity

            let lastFoundActivity: number
            lastActivityCheck = setInterval(() => {
                const stalenessCheckResult = stalenessCheck(hub, serverConfig.STALENESS_RESTART_SECONDS)

                if (
                    hub?.lastActivity &&
                    stalenessCheckResult.isServerStale &&
                    lastFoundActivity !== hub?.lastActivity
                ) {
                    lastFoundActivity = hub?.lastActivity
                    const extra = {
                        piscina: piscina ? JSON.stringify(getPiscinaStats(piscina)) : null,
                        ...stalenessCheckResult,
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
                    hub?.statsd?.increment(`alerts.stale_plugin_server_restarted`)

                    killProcess()
                }
            }, Math.min(serverConfig.STALENESS_RESTART_SECONDS, 10000))
        }

        serverInstance.piscina = piscina
        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        healthCheckConsumer = await setupKafkaHealthcheckConsumer(hub.kafka)
        serverInstance.kafkaHealthcheckConsumer = healthCheckConsumer

        await healthCheckConsumer.connect()

        try {
            healthCheckConsumer.pause([{ topic: KAFKA_HEALTHCHECK }])
        } catch (err) {
            // It's fine to do nothing for now - Kafka issues will be caught by the periodic healthcheck
            status.error('🔴', 'Failed to pause Kafka healthcheck consumer on connect!')
        }

        if (hub.capabilities.http) {
            // start http server used for the healthcheck
            httpServer = createHttpServer(hub!, serverInstance as ServerInstance, serverConfig)
        }

        hub.statsd?.timing('total_setup_time', timer)
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
    // Wait 2 seconds to flush the last queues and caches
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
    await piscina.destroy()
}
