import { CyclotronMetricsConfig, initCyclotronMetrics } from '@posthog/cyclotron'
import * as Sentry from '@sentry/node'
import fs from 'fs'
import { Server } from 'http'
import { CompressionCodecs, CompressionTypes, KafkaJSProtocolError } from 'kafkajs'
// @ts-expect-error no type definitions
import SnappyCodec from 'kafkajs-snappy'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import v8Profiler from 'v8-profiler-next'

import { getPluginServerCapabilities } from '../capabilities'
import { CdpApi } from '../cdp/cdp-api'
import {
    CdpCyclotronWorker,
    CdpCyclotronWorkerFetch,
    CdpFunctionCallbackConsumer,
    CdpProcessedEventsConsumer,
} from '../cdp/cdp-consumers'
import { defaultConfig, sessionRecordingConsumerConfig } from '../config/config'
import { Hub, PluginServerCapabilities, PluginServerService, PluginsServerConfig } from '../types'
import { closeHub, createHub, createKafkaClient, createKafkaProducerWrapper } from '../utils/db/hub'
import { PostgresRouter } from '../utils/db/postgres'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { posthog } from '../utils/posthog'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { createRedisClient, delay } from '../utils/utils'
import { ActionManager } from '../worker/ingestion/action-manager'
import { ActionMatcher } from '../worker/ingestion/action-matcher'
import { AppMetrics } from '../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../worker/ingestion/organization-manager'
import { TeamManager } from '../worker/ingestion/team-manager'
import Piscina, { makePiscina as defaultMakePiscina } from '../worker/piscina'
import { RustyHook } from '../worker/rusty-hook'
import { syncInlinePlugins } from '../worker/vm/inline/inline'
import { GraphileWorker } from './graphile-worker/graphile-worker'
import { loadPluginSchedule } from './graphile-worker/schedule'
import { startGraphileWorker } from './graphile-worker/worker-setup'
import { startAnalyticsEventsIngestionConsumer } from './ingestion-queues/analytics-events-ingestion-consumer'
import { startAnalyticsEventsIngestionHistoricalConsumer } from './ingestion-queues/analytics-events-ingestion-historical-consumer'
import { startAnalyticsEventsIngestionOverflowConsumer } from './ingestion-queues/analytics-events-ingestion-overflow-consumer'
import { PIPELINES, startEventsIngestionPipelineConsumer } from './ingestion-queues/events-ingestion-consumer'
import { startJobsConsumer } from './ingestion-queues/jobs-consumer'
import {
    startAsyncOnEventHandlerConsumer,
    startAsyncWebhooksHandlerConsumer,
} from './ingestion-queues/on-event-handler-consumer'
import { startScheduledTasksConsumer } from './ingestion-queues/scheduled-tasks-consumer'
import { SessionRecordingIngester } from './ingestion-queues/session-recording/session-recordings-consumer'
import { expressApp, setupCommonRoutes } from './services/http-server'
import { getObjectStorage } from './services/object_storage'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

const { version } = require('../../package.json')

export type ServerInstance = {
    hub?: Hub
    stop: () => Promise<void>
}

const pluginServerStartupTimeMs = new Counter({
    name: 'plugin_server_startup_time_ms',
    help: 'Time taken to start the plugin server, in milliseconds',
})

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (serverConfig: PluginsServerConfig, hub: Hub) => Promise<Piscina> = defaultMakePiscina,
    capabilities?: PluginServerCapabilities
): Promise<ServerInstance> {
    const timer = new Date()

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)
    runStartupProfiles(serverConfig)

    // Used to trigger reloads of plugin code/config
    let pubSub: PubSub | undefined

    // A Node Worker Thread pool
    let piscina: Piscina | undefined

    const services: PluginServerService[] = []

    // Kafka consumer. Handles events that we couldn't find an existing person
    // to associate. The buffer handles delaying the ingestion of these events
    // (default 60 seconds) to allow for the person to be created in the
    // meantime.
    let httpServer: Server | undefined // server
    let graphileWorker: GraphileWorker | undefined
    let lastActivityCheck: NodeJS.Timeout | undefined
    let stopEventLoopMetrics: (() => void) | undefined

    let shuttingDown = false
    async function closeJobs(): Promise<void> {
        shuttingDown = true
        status.info('💤', ' Shutting down gracefully...')
        lastActivityCheck && clearInterval(lastActivityCheck)

        // HACKY: Stop all consumers and the graphile worker, as well as the
        // http server. Note that we close the http server before the others to
        // ensure that e.g. if something goes wrong and we deadlock, then if
        // we're running in k8s, the liveness check will fail, and thus k8s will
        // kill the pod.
        //
        // I say hacky because we've got a weak dependency on the liveness check
        // configuration.
        httpServer?.close()
        cancelAllScheduledJobs()
        stopEventLoopMetrics?.()
        await Promise.allSettled([
            pubSub?.stop(),
            graphileWorker?.stop(),
            ...services.map((service) => service.onShutdown()),
            posthog.shutdownAsync(),
        ])

        if (piscina) {
            await stopPiscina(piscina)
        }

        if (serverInstance.hub) {
            await closeHub(serverInstance.hub)
        }
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        status.info('👋', 'process handling beforeExit event. Closing jobs...')
        await closeJobs()
        status.info('👋', 'Over and out!')
        process.exit(0)
    })

    // Code list in https://kafka.apache.org/0100/protocol.html
    const kafkaJSIgnorableCodes = new Set([
        22, // ILLEGAL_GENERATION
        25, // UNKNOWN_MEMBER_ID
        27, // REBALANCE_IN_PROGRESS
    ])

    process.on('unhandledRejection', (error: Error | any, promise: Promise<any>) => {
        status.error('🤮', `Unhandled Promise Rejection`, { error, promise })

        if (error instanceof KafkaJSProtocolError) {
            kafkaProtocolErrors.inc({
                type: error.type,
                code: error.code,
            })

            // Ignore some "business as usual" Kafka errors, send the rest to sentry
            if (error.code in kafkaJSIgnorableCodes) {
                return
            }
        }

        Sentry.captureException(error, {
            extra: { detected_at: `pluginServer.ts on unhandledRejection` },
        })
    })

    process.on('uncaughtException', async (error: Error) => {
        // If there are unhandled exceptions anywhere, perform a graceful
        // shutdown. The initial trigger for including this handler is due to
        // the graphile-worker code throwing an exception when it can't call
        // `nudge` on a worker. Unsure as to why this happens, but at any rate,
        // to ensure that we gracefully shutdown Kafka consumers, for which
        // unclean shutdowns can cause considerable delay in starting to consume
        // again, we try to gracefully shutdown.
        //
        // See https://nodejs.org/api/process.html#event-uncaughtexception for
        // details on the handler.
        if (shuttingDown) {
            return
        }
        status.error('🤮', `uncaught_exception`, { error: error.stack })
        await closeJobs()

        process.exit(1)
    })

    capabilities = capabilities ?? getPluginServerCapabilities(serverConfig)
    const serverInstance: ServerInstance = {
        stop: closeJobs,
    }

    const setupHub = async (): Promise<Hub> => {
        if (!serverInstance.hub) {
            serverInstance.hub = await createHub(serverConfig, capabilities)
        }

        return serverInstance.hub
    }

    // Creating a dedicated single-connection redis client to this Redis, as it's not relevant for hobby
    // and cloud deploys don't have concurrent uses. We should abstract multi-Redis into a router util.
    const captureRedis = serverConfig.CAPTURE_CONFIG_REDIS_HOST
        ? await createRedisClient(serverConfig.CAPTURE_CONFIG_REDIS_HOST)
        : undefined

    try {
        // Based on the mode the plugin server was started, we start a number of
        // different services. Mostly this is reasonably obvious from the name.
        // There is however the `queue` which is a little more complicated.
        // Depending on the capabilities we start with, it will either consume
        // from:
        //
        // 1. plugin_events_ingestion
        // 2. clickhouse_events_json
        // 3. clickhouse_events_json and plugin_events_ingestion
        // 4. conversion_events_buffer
        //
        if (capabilities.processPluginJobs || capabilities.pluginScheduledTasks) {
            const hub = await setupHub()

            graphileWorker = new GraphileWorker(hub)
            // `connectProducer` just runs the PostgreSQL migrations. Ideally it
            // would be great to move the migration to bin/migrate and ensure we
            // have a way for the pods to wait for the migrations to complete as
            // we do with other migrations. However, I couldn't find a
            // `graphile-worker` supported way to do this, and I don't think
            // it's that heavy so it may be fine, but something to watch out
            // for.
            await graphileWorker.connectProducer()
            piscina = piscina ?? (await makePiscina(serverConfig, hub))
            status.info('👷', 'Starting graphile worker...')
            await startGraphileWorker(hub, graphileWorker, piscina)
            status.info('👷', 'Graphile worker is ready!')

            if (capabilities.pluginScheduledTasks) {
                services.push(
                    await startScheduledTasksConsumer({
                        piscina: piscina,
                        producer: hub.kafkaProducer,
                        kafka: hub.kafka,
                        serverConfig,
                        partitionConcurrency: serverConfig.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                    })
                )
            }

            if (capabilities.processPluginJobs) {
                services.push(
                    await startJobsConsumer({
                        kafka: hub.kafka,
                        producer: hub.kafkaProducer,
                        graphileWorker: graphileWorker,
                        serverConfig,
                    })
                )
            }
        }

        if (capabilities.ingestion) {
            const hub = await setupHub()
            piscina = piscina ?? (await makePiscina(serverConfig, hub))
            services.push(
                await startAnalyticsEventsIngestionConsumer({
                    hub: hub,
                })
            )
        }

        if (capabilities.ingestionHistorical) {
            const hub = await setupHub()
            piscina = piscina ?? (await makePiscina(serverConfig, hub))
            services.push(
                await startAnalyticsEventsIngestionHistoricalConsumer({
                    hub: hub,
                })
            )
        }

        if (capabilities.eventsIngestionPipelines) {
            const pipelinesToRun =
                serverConfig.PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE === null
                    ? Object.keys(PIPELINES)
                    : [serverConfig.PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE]

            for (const pipelineKey of pipelinesToRun) {
                if (pipelineKey === null || !PIPELINES[pipelineKey]) {
                    throw new Error(`Invalid events ingestion pipeline: ${pipelineKey}`)
                }

                const hub = await setupHub()
                piscina = piscina ?? (await makePiscina(serverConfig, hub))
                services.push(
                    await startEventsIngestionPipelineConsumer({
                        hub: hub,
                        pipelineKey: pipelineKey,
                    })
                )
            }
        }

        if (capabilities.ingestionOverflow) {
            const hub = await setupHub()
            piscina = piscina ?? (await makePiscina(serverConfig, hub))
            services.push(
                await startAnalyticsEventsIngestionOverflowConsumer({
                    hub: hub,
                })
            )
        }

        if (capabilities.processAsyncOnEventHandlers) {
            const hub = await setupHub()
            piscina = piscina ?? (await makePiscina(serverConfig, hub))
            services.push(
                await startAsyncOnEventHandlerConsumer({
                    hub: hub,
                })
            )
        }

        if (capabilities.processAsyncWebhooksHandlers) {
            const hub = serverInstance.hub
            // If we have a hub, then reuse some of it's attributes, otherwise
            // we need to create them. We only initialize the ones we need.
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const kafka = hub?.kafka ?? createKafkaClient(serverConfig)
            const teamManager = hub?.teamManager ?? new TeamManager(postgres, serverConfig)
            const organizationManager = hub?.organizationManager ?? new OrganizationManager(postgres, teamManager)
            const KafkaProducerWrapper = hub?.kafkaProducer ?? (await createKafkaProducerWrapper(serverConfig))
            const rustyHook = hub?.rustyHook ?? new RustyHook(serverConfig)
            const appMetrics =
                hub?.appMetrics ??
                new AppMetrics(
                    KafkaProducerWrapper,
                    serverConfig.APP_METRICS_FLUSH_FREQUENCY_MS,
                    serverConfig.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
                )

            const actionManager = hub?.actionManager ?? new ActionManager(postgres, serverConfig)
            const actionMatcher = hub?.actionMatcher ?? new ActionMatcher(postgres, actionManager, teamManager)
            const groupTypeManager = new GroupTypeManager(postgres, teamManager, serverConfig.SITE_URL)

            services.push(
                await startAsyncWebhooksHandlerConsumer({
                    postgres,
                    kafka,
                    teamManager,
                    organizationManager,
                    serverConfig,
                    rustyHook,
                    appMetrics,
                    actionMatcher,
                    actionManager,
                    groupTypeManager,
                })
            )
        }

        if (capabilities.syncInlinePlugins) {
            const hub = await setupHub()

            await syncInlinePlugins(hub)
        }

        if (serverInstance.hub) {
            const hub = serverInstance.hub
            pubSub = new PubSub(hub, {
                [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                    status.info('⚡', 'Reloading plugins!')
                    await piscina?.broadcastTask({ task: 'reloadPlugins' })

                    if (hub?.capabilities.pluginScheduledTasks && piscina) {
                        await piscina.broadcastTask({ task: 'reloadSchedule' })
                        hub.pluginSchedule = await loadPluginSchedule(piscina)
                    }
                },
                'reset-available-product-features-cache': async (message) => {
                    await piscina?.broadcastTask({
                        task: 'resetAvailableProductFeaturesCache',
                        args: JSON.parse(message),
                    })
                },
                'populate-plugin-capabilities': async (message) => {
                    // We need this to be done in only once
                    if (hub?.capabilities.appManagementSingleton && piscina) {
                        await piscina?.broadcastTask({ task: 'populatePluginCapabilities', args: JSON.parse(message) })
                    }
                },
            })

            await pubSub.start()

            if (capabilities.preflightSchedules) {
                startPreflightSchedules(hub)
            }

            serverInstance.stop = closeJobs

            pluginServerStartupTimeMs.inc(Date.now() - timer.valueOf())
            status.info('🚀', 'All systems go')
        }

        if (capabilities.sessionRecordingBlobIngestion) {
            const hub = serverInstance.hub
            const recordingConsumerConfig = sessionRecordingConsumerConfig(serverConfig)
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const s3 = hub?.objectStorage ?? getObjectStorage(recordingConsumerConfig)

            if (!s3) {
                throw new Error("Can't start session recording blob ingestion without object storage")
            }
            // NOTE: We intentionally pass in the original serverConfig as the ingester uses both kafkas
            const ingester = new SessionRecordingIngester(serverConfig, postgres, s3, false, captureRedis)
            await ingester.start()

            services.push({
                id: 'session-recordings-blob',
                onShutdown: async () => await ingester.stop(),
                healthcheck: () => ingester.isHealthy() ?? false,
                batchConsumer: ingester.batchConsumer,
            })
        }

        if (capabilities.sessionRecordingBlobOverflowIngestion) {
            const hub = serverInstance.hub
            const recordingConsumerConfig = sessionRecordingConsumerConfig(serverConfig)
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const s3 = hub?.objectStorage ?? getObjectStorage(recordingConsumerConfig)

            if (!s3) {
                throw new Error("Can't start session recording blob ingestion without object storage")
            }
            // NOTE: We intentionally pass in the original serverConfig as the ingester uses both kafkas
            // NOTE: We don't pass captureRedis to disable overflow computation on the overflow topic
            const ingester = new SessionRecordingIngester(serverConfig, postgres, s3, true, undefined)
            await ingester.start()
            services.push(ingester.service)
        }

        if (capabilities.cdpProcessedEvents) {
            const hub = await setupHub()
            const consumer = new CdpProcessedEventsConsumer(hub)
            await consumer.start()
            services.push(consumer.service)
        }

        if (capabilities.cdpFunctionCallbacks) {
            const hub = await setupHub()
            const consumer = new CdpFunctionCallbackConsumer(hub)
            await consumer.start()
            services.push(consumer.service)

            // NOTE: The function callback service is more idle so can handle http requests as well
            if (capabilities.http) {
                const api = new CdpApi(hub, consumer)
                expressApp.use('/', api.router())
            }
        }

        if (capabilities.cdpCyclotronWorker) {
            const hub = await setupHub()

            if (!hub.CYCLOTRON_DATABASE_URL) {
                status.error('💥', 'Cyclotron database URL not set.')
            } else {
                const worker = new CdpCyclotronWorker(hub)
                await worker.start()
                services.push(worker.service)

                if (process.env.EXPERIMENTAL_CDP_FETCH_WORKER) {
                    const workerFetch = new CdpCyclotronWorkerFetch(hub)
                    await workerFetch.start()
                    services.push(workerFetch.service)
                }
            }
        }

        if (capabilities.http) {
            const app = setupCommonRoutes(services)

            httpServer = app.listen(serverConfig.HTTP_SERVER_PORT, () => {
                status.info('🩺', `Status server listening on port ${serverConfig.HTTP_SERVER_PORT}`)
            })
        }

        // If join rejects or throws, then the consumer is unhealthy and we should shut down the process.
        // Ideally we would also join all the other background tasks as well to ensure we stop the
        // server if we hit any errors and don't end up with zombie instances, but I'll leave that
        // refactoring for another time. Note that we have the liveness health checks already, so in K8s
        // cases zombies should be reaped anyway, albeit not in the most efficient way.

        services.forEach((service) => {
            service.batchConsumer?.join().catch(async (error) => {
                status.error('💥', 'Unexpected task joined!', { error: error.stack ?? error })
                await closeJobs()
                process.exit(1)
            })
        })

        if (cyclotronInUse(await setupHub())) {
            const labels = new Map()
            labels.set('plugin_server_version', version)
            labels.set('plugin_server_mode', serverConfig.PLUGIN_SERVER_MODE)
            const config: CyclotronMetricsConfig = {
                defaultLabels: labels,
            }
            initCyclotronMetrics(config)
        }

        return serverInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        status.error('💥', 'Exception while starting server, shutting down!', { error })
        await closeJobs()
        process.exit(1)
    }
}

const startPreflightSchedules = (hub: Hub) => {
    // These are used by the preflight checks in the Django app to determine if
    // the plugin-server is running.
    schedule.scheduleJob('*/5 * * * * *', async () => {
        await hub.db.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 'preflightSchedules', 60, {
            jsonSerialize: false,
        })
        await hub.db.redisSet('@posthog-plugin-server/version', version, 'preflightSchedules', undefined, {
            jsonSerialize: false,
        })
    })
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait *up to* 5 seconds to shut down VMs.
    await Promise.race([piscina.broadcastTask({ task: 'teardownPlugins' }), delay(5000)])
    // Wait 2 seconds to flush the last queues and caches
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
}

const kafkaProtocolErrors = new Counter({
    name: 'kafka_protocol_errors_total',
    help: 'Kafka protocol errors encountered, by type',
    labelNames: ['type', 'code'],
})

function runStartupProfiles(config: PluginsServerConfig) {
    if (config.STARTUP_PROFILE_CPU) {
        status.info('🩺', `Collecting cpu profile...`)
        v8Profiler.setGenerateType(1)
        v8Profiler.startProfiling('startup', true)
        setTimeout(() => {
            const profile = v8Profiler.stopProfiling('startup')
            fs.writeFileSync('./startup.cpuprofile', JSON.stringify(profile))
            status.info('🩺', `Wrote cpu profile to disk`)
            profile.delete()
        }, config.STARTUP_PROFILE_DURATION_SECONDS * 1000)
    }
    if (config.STARTUP_PROFILE_HEAP) {
        status.info('🩺', `Collecting heap profile...`)
        v8Profiler.startSamplingHeapProfiling(config.STARTUP_PROFILE_HEAP_INTERVAL, config.STARTUP_PROFILE_HEAP_DEPTH)
        setTimeout(() => {
            const profile = v8Profiler.stopSamplingHeapProfiling()
            fs.writeFileSync('./startup.heapprofile', JSON.stringify(profile))
            status.info('🩺', `Wrote heap profile to disk`)
        }, config.STARTUP_PROFILE_DURATION_SECONDS * 1000)
    }
}

function cyclotronInUse(hub: Hub): boolean {
    const urlSet = hub.CYCLOTRON_DATABASE_URL ? true : false
    const cdpProcessedEvents = hub.capabilities.cdpProcessedEvents ? true : false
    const cdpCyclotronWorker = hub.capabilities.cdpCyclotronWorker ? true : false

    return (urlSet && cdpProcessedEvents) || cdpCyclotronWorker
}
