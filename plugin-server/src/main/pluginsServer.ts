import * as Sentry from '@sentry/node'
import fs from 'fs'
import { Server } from 'http'
import { CompressionCodecs, CompressionTypes } from 'kafkajs'
// @ts-expect-error no type definitions
import SnappyCodec from 'kafkajs-snappy'
import LZ4 from 'lz4-kafkajs'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import v8Profiler from 'v8-profiler-next'

import { getPluginServerCapabilities } from '../capabilities'
import { CdpApi } from '../cdp/cdp-api'
import { CdpCyclotronWorkerPlugins } from '../cdp/consumers/cdp-cyclotron-plugins-worker.consumer'
import { CdpCyclotronWorker, CdpCyclotronWorkerFetch } from '../cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpInternalEventsConsumer } from '../cdp/consumers/cdp-internal-event.consumer'
import { CdpProcessedEventsConsumer } from '../cdp/consumers/cdp-processed-events.consumer'
import { defaultConfig } from '../config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { IngestionConsumer } from '../ingestion/ingestion-consumer'
import { Config, Hub, PluginServerCapabilities, PluginServerService } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisClient } from '../utils/db/redis'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { posthog } from '../utils/posthog'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { delay } from '../utils/utils'
import { SessionRecordingIngester } from './ingestion-queues/session-recording/session-recordings-consumer'
import { DefaultBatchConsumerFactory } from './ingestion-queues/session-recording-v2/batch-consumer-factory'
import { SessionRecordingIngester as SessionRecordingIngesterV2 } from './ingestion-queues/session-recording-v2/consumer'
import { expressApp, setupCommonRoutes } from './services/http-server'
import { getObjectStorage } from './services/object_storage'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec
CompressionCodecs[CompressionTypes.LZ4] = new LZ4().codec

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
    config: Partial<Config>,
    capabilities?: PluginServerCapabilities
): Promise<ServerInstance> {
    const timer = new Date()

    const serverConfig: Config = {
        ...defaultConfig,
        ...config,
    }

    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    runStartupProfiles(serverConfig)

    // Used to trigger reloads of plugin code/config
    let pubSub: PubSub | undefined

    const services: PluginServerService[] = []

    // Kafka consumer. Handles events that we couldn't find an existing person
    // to associate. The buffer handles delaying the ingestion of these events
    // (default 60 seconds) to allow for the person to be created in the
    // meantime.
    let httpServer: Server | undefined // server
    let lastActivityCheck: NodeJS.Timeout | undefined
    let stopEventLoopMetrics: (() => void) | undefined

    let shuttingDown = false
    async function shutdown(): Promise<void> {
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
            ...services.map((service) => service.onShutdown()),
            posthog.shutdownAsync(),
        ])

        if (serverInstance.hub) {
            // Wait 2 seconds to flush the last queues and caches
            await Promise.all([serverInstance.hub?.kafkaProducer.flush(), delay(2000)])
            await closeHub(serverInstance.hub)
        }
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        status.info('👋', 'process handling beforeExit event. Closing jobs...')
        await shutdown()
        status.info('👋', 'Over and out!')
        process.exit(0)
    })

    process.on('unhandledRejection', (error: Error | any, promise: Promise<any>) => {
        status.error('🤮', `Unhandled Promise Rejection`, { error, promise })

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
        await shutdown()

        process.exit(1)
    })

    capabilities = capabilities ?? getPluginServerCapabilities(serverConfig)
    const hub = await createHub(serverConfig, capabilities)

    const serverInstance: ServerInstance = {
        hub,
        stop: shutdown,
    }

    // Creating a dedicated single-connection redis client to this Redis, as it's not relevant for hobby
    // and cloud deploys don't have concurrent uses. We should abstract multi-Redis into a router util.
    const captureRedis = serverConfig.CAPTURE_CONFIG_REDIS_HOST
        ? await createRedisClient(serverConfig.CAPTURE_CONFIG_REDIS_HOST)
        : undefined

    try {
        if (capabilities.ingestionV2Combined) {
            // NOTE: This is for single process deployments like local dev and hobby - it runs all possible consumers
            // in a single process. In production these are each separate Deployments of the standard ingestion consumer

            const consumersOptions = [
                {
                    topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                    group_id: `clickhouse-ingestion`,
                },
                {
                    topic: KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
                    group_id: `clickhouse-ingestion-historical`,
                },
                { topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, group_id: 'clickhouse-ingestion-overflow' },
                { topic: 'client_iwarnings_ingestion', group_id: 'client_iwarnings_ingestion' },
                { topic: 'heatmaps_ingestion', group_id: 'heatmaps_ingestion' },
                { topic: 'exceptions_ingestion', group_id: 'exceptions_ingestion' },
            ]

            for (const consumerOption of consumersOptions) {
                const modifiedHub: Hub = {
                    ...hub,
                    INGESTION_CONSUMER_CONSUME_TOPIC: consumerOption.topic,
                    INGESTION_CONSUMER_GROUP_ID: consumerOption.group_id,
                }

                const consumer = new IngestionConsumer(modifiedHub)
                await consumer.start()
                services.push(consumer.service)
            }
        } else {
            if (capabilities.ingestionV2) {
                // NOTE: Piscina is only needed whilst we have legacy plugins running. Once we have all
                // moved to hog functions we can remove this.
                const consumer = new IngestionConsumer(hub)
                await consumer.start()
                services.push(consumer.service)
            }
        }

        if (capabilities.sessionRecordingBlobIngestion) {
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const s3 = hub?.objectStorage ?? getObjectStorage(serverConfig)

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
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const s3 = hub?.objectStorage ?? getObjectStorage(serverConfig)

            if (!s3) {
                throw new Error("Can't start session recording blob ingestion without object storage")
            }
            // NOTE: We intentionally pass in the original serverConfig as the ingester uses both kafkas
            // NOTE: We don't pass captureRedis to disable overflow computation on the overflow topic
            const ingester = new SessionRecordingIngester(serverConfig, postgres, s3, true, undefined)
            await ingester.start()
            services.push(ingester.service)
        }

        if (capabilities.sessionRecordingBlobIngestionV2) {
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const batchConsumerFactory = new DefaultBatchConsumerFactory(serverConfig)
            const ingester = new SessionRecordingIngesterV2(serverConfig, false, postgres, batchConsumerFactory)
            await ingester.start()
            services.push(ingester.service)
        }

        if (capabilities.sessionRecordingBlobIngestionV2Overflow) {
            const postgres = hub?.postgres ?? new PostgresRouter(serverConfig)
            const batchConsumerFactory = new DefaultBatchConsumerFactory(serverConfig)
            const ingester = new SessionRecordingIngesterV2(serverConfig, true, postgres, batchConsumerFactory)
            await ingester.start()
            services.push(ingester.service)
        }

        if (capabilities.cdpProcessedEvents) {
            const consumer = new CdpProcessedEventsConsumer(hub)
            await consumer.start()
            services.push(consumer.service)
        }

        if (capabilities.cdpInternalEvents) {
            const consumer = new CdpInternalEventsConsumer(hub)
            await consumer.start()
            services.push(consumer.service)
        }

        if (capabilities.cdpApi) {
            const api = new CdpApi(hub)
            await api.start()
            services.push(api.service)
            expressApp.use('/', api.router())
        }

        if (capabilities.cdpCyclotronWorker) {
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

        if (capabilities.cdpCyclotronWorkerPlugins) {
            if (!hub.CYCLOTRON_DATABASE_URL) {
                status.error('💥', 'Cyclotron database URL not set.')
            } else {
                const worker = new CdpCyclotronWorkerPlugins(hub)
                await worker.start()
                services.push(worker.service)
            }
        }

        if (capabilities.http) {
            const app = setupCommonRoutes(services)

            httpServer = app.listen(serverConfig.HTTP_SERVER_PORT, () => {
                status.info('🩺', `Status server listening on port ${serverConfig.HTTP_SERVER_PORT}`)
            })
        }

        pubSub = new PubSub(hub, {
            'reset-available-product-features-cache': (message) => {
                // TODO: Can we make this nicer?
                hub.organizationManager.resetAvailableProductFeaturesCache(JSON.parse(message).organization_id)
            },
        })

        await pubSub.start()

        pluginServerStartupTimeMs.inc(Date.now() - timer.valueOf())
        status.info('🚀', 'All systems go')

        // If join rejects or throws, then the consumer is unhealthy and we should shut down the process.
        // Ideally we would also join all the other background tasks as well to ensure we stop the
        // server if we hit any errors and don't end up with zombie instances, but I'll leave that
        // refactoring for another time. Note that we have the liveness health checks already, so in K8s
        // cases zombies should be reaped anyway, albeit not in the most efficient way.

        services.forEach((service) => {
            service.batchConsumer?.join().catch(async (error) => {
                status.error('💥', 'Unexpected task joined!', { error: error.stack ?? error })
                await shutdown()
                process.exit(1)
            })
        })

        return serverInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        status.error('💥', 'Exception while starting server, shutting down!', { error })
        await shutdown()
        process.exit(1)
    }
}

function runStartupProfiles(config: Config) {
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
