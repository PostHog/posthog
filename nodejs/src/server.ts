import * as Pyroscope from '@pyroscope/nodejs'
import { Server } from 'http'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { setupCommonRoutes, setupExpressApp } from './api/router'
import { getPluginServerCapabilities } from './capabilities'
import { CdpApi } from './cdp/cdp-api'
import { CdpCohortMembershipConsumer } from './cdp/consumers/cdp-cohort-membership.consumer'
import { CdpCyclotronDelayConsumer } from './cdp/consumers/cdp-cyclotron-delay.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpCyclotronWorker } from './cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpDatawarehouseEventsConsumer } from './cdp/consumers/cdp-data-warehouse-events.consumer'
import { CdpEventsConsumer } from './cdp/consumers/cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp/consumers/cdp-internal-event.consumer'
import { CdpLegacyEventsConsumer } from './cdp/consumers/cdp-legacy-event.consumer'
import { CdpPersonUpdatesConsumer } from './cdp/consumers/cdp-person-updates-consumer'
import { CdpPrecalculatedFiltersConsumer } from './cdp/consumers/cdp-precalculated-filters.consumer'
import { defaultConfig } from './config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from './config/kafka-topics'
import { startEvaluationScheduler } from './evaluation-scheduler/evaluation-scheduler'
import { IngestionConsumer } from './ingestion/ingestion-consumer'
import { onShutdown } from './lifecycle'
import { LogsIngestionConsumer } from './logs-ingestion/logs-ingestion-consumer'
import { SessionRecordingIngester } from './session-recording/consumer'
import { Hub, PluginServerService, PluginsServerConfig } from './types'
import { ServerCommands } from './utils/commands'
import { closeHub, createHub } from './utils/db/hub'
import { isTestEnv } from './utils/env-utils'
import { logger } from './utils/logger'
import { NodeInstrumentation } from './utils/node-instrumentation'
import { captureException, shutdown as posthogShutdown } from './utils/posthog'
import { PubSub } from './utils/pubsub'
import { delay } from './utils/utils'

const pluginServerStartupTimeMs = new Counter({
    name: 'plugin_server_startup_time_ms',
    help: 'Time taken to start the nodejs service, in milliseconds',
})

export class PluginServer {
    config: PluginsServerConfig
    pubsub?: PubSub
    services: PluginServerService[] = []
    httpServer?: Server
    stopping = false
    hub?: Hub
    expressApp: express.Application
    nodeInstrumentation: NodeInstrumentation
    private podTerminationTimer?: NodeJS.Timeout

    constructor(
        config: Partial<PluginsServerConfig> = {},
        private options: {
            disableHttpServer?: boolean
        } = {}
    ) {
        this.config = {
            ...defaultConfig,
            ...config,
        }

        this.expressApp = setupExpressApp()
        this.nodeInstrumentation = new NodeInstrumentation(this.config)
        this.setupContinuousProfiling()
    }

    private setupPodTermination(): void {
        // Base timeout from config (convert minutes to milliseconds)
        const baseTimeoutMs = this.config.POD_TERMINATION_BASE_TIMEOUT_MINUTES * 60 * 1000

        // Add jitter: random value between 0 and configured jitter (convert minutes to milliseconds)
        const jitterMs = Math.random() * this.config.POD_TERMINATION_JITTER_MINUTES * 60 * 1000

        const totalTimeoutMs = baseTimeoutMs + jitterMs

        logger.info('⏰', `Pod termination scheduled in ${Math.round(totalTimeoutMs / 1000 / 60)} minutes`)

        this.podTerminationTimer = setTimeout(() => {
            logger.info('⏰', 'Pod termination timeout reached, shutting down gracefully...')
            void this.stop()
        }, totalTimeoutMs)
    }

    async start(): Promise<void> {
        const startupTimer = new Date()
        this.setupListeners()
        this.nodeInstrumentation.setupThreadPerformanceInterval()

        const capabilities = getPluginServerCapabilities(this.config)
        const hub = (this.hub = await createHub(this.config))

        try {
            const serviceLoaders: (() => Promise<PluginServerService>)[] = []

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
                ]

                for (const consumerOption of consumersOptions) {
                    serviceLoaders.push(async () => {
                        const consumer = new IngestionConsumer(hub, {
                            INGESTION_CONSUMER_CONSUME_TOPIC: consumerOption.topic,
                            INGESTION_CONSUMER_GROUP_ID: consumerOption.group_id,
                        })
                        await consumer.start()
                        return consumer.service
                    })
                }
            } else if (capabilities.ingestionV2) {
                serviceLoaders.push(async () => {
                    const consumer = new IngestionConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.evaluationScheduler) {
                serviceLoaders.push(() => startEvaluationScheduler(hub))
            }

            if (capabilities.sessionRecordingBlobIngestionV2) {
                serviceLoaders.push(async () => {
                    const actualHub = hub ?? (await createHub(this.config))
                    const postgres = actualHub.postgres
                    const producer = actualHub.kafkaProducer

                    const ingester = new SessionRecordingIngester(actualHub, false, postgres, producer)
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.sessionRecordingBlobIngestionV2Overflow) {
                serviceLoaders.push(async () => {
                    const actualHub = hub ?? (await createHub(this.config))
                    const postgres = actualHub.postgres
                    const producer = actualHub.kafkaProducer

                    const ingester = new SessionRecordingIngester(actualHub, true, postgres, producer)
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.cdpProcessedEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpDataWarehouseEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpDatawarehouseEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpInternalEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpInternalEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpPersonUpdates) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpPersonUpdatesConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpLegacyOnEvent) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpLegacyEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpApi) {
                serviceLoaders.push(async () => {
                    const api = new CdpApi(hub)
                    this.expressApp.use('/', api.router())
                    await api.start()
                    return api.service
                })
            }

            if (capabilities.cdpCyclotronWorker) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorker(hub)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCyclotronWorkerHogFlow) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorkerHogFlow(hub)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCyclotronWorkerDelay) {
                serviceLoaders.push(async () => {
                    const delayConsumer = new CdpCyclotronDelayConsumer(hub)
                    await delayConsumer.start()
                    return delayConsumer.service
                })
            }

            // The service commands is always created
            serviceLoaders.push(() => {
                const serverCommands = new ServerCommands(hub)
                this.expressApp.use('/', serverCommands.router())
                return Promise.resolve(serverCommands.service)
            })

            if (capabilities.cdpPrecalculatedFilters) {
                serviceLoaders.push(async () => {
                    const worker = new CdpPrecalculatedFiltersConsumer(hub)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCohortMembership) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpCohortMembershipConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.logsIngestion) {
                serviceLoaders.push(async () => {
                    const consumer = new LogsIngestionConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
            this.services.push(...readyServices)

            setupCommonRoutes(this.expressApp, this.services)

            if (!isTestEnv()) {
                // We don't run http server in test env currently
                this.httpServer = this.expressApp.listen(this.config.HTTP_SERVER_PORT, () => {
                    logger.info('🩺', `HTTP server listening on port ${this.config.HTTP_SERVER_PORT}`)
                })
            }

            pluginServerStartupTimeMs.inc(Date.now() - startupTimer.valueOf())
            logger.info('🚀', `All systems go in ${Date.now() - startupTimer.valueOf()}ms`)

            // Setup pod termination if enabled
            if (this.config.POD_TERMINATION_ENABLED) {
                this.setupPodTermination()
            }
        } catch (error) {
            captureException(error)
            logger.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
            logger.error('💥', 'Exception while starting server, shutting down!', { error })
            await this.stop(error)
        }
    }

    private setupListeners(): void {
        for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
            process.on(signal, async () => {
                // This makes async exit possible with the process waiting until jobs are closed
                logger.info('👋', `process handling ${signal} event. Stopping...`)
                await this.stop()
            })
        }

        process.on('unhandledRejection', (error: Error | any) => {
            logger.error('🤮', `Unhandled Promise Rejection`, { error: String(error) })

            captureException(error, {
                extra: { detected_at: `pluginServer.ts on unhandledRejection` },
            })

            void this.stop(error)
        })

        process.on('uncaughtException', async (error: Error) => {
            await this.stop(error)
        })
    }

    async stop(error?: Error): Promise<void> {
        if (error) {
            logger.error('🤮', `Shutting down due to error`, { error: error.stack })
        }
        if (this.stopping) {
            logger.info('🚨', 'Stop called but already stopping...')
            return
        }

        this.stopping = true

        // Clear pod termination timer if it exists
        if (this.podTerminationTimer) {
            clearTimeout(this.podTerminationTimer)
            this.podTerminationTimer = undefined
        }

        this.nodeInstrumentation.cleanup()

        logger.info('💤', ' Shutting down gracefully...')

        this.httpServer?.close()
        Object.values(schedule.scheduledJobs).forEach((job) => {
            job.cancel()
        })

        logger.info('💤', ' Shutting down services...')
        await Promise.allSettled([
            this.pubsub?.stop(),
            ...this.services.map((s) => s.onShutdown()),
            posthogShutdown(),
            onShutdown(),
        ])

        if (this.hub) {
            logger.info('💤', ' Shutting down kafka producer...')
            // Wait 2 seconds to flush the last queues and caches
            await Promise.all([this.hub?.kafkaProducer.flush(), delay(2000)])
            await closeHub(this.hub)
        }

        logger.info('💤', ' Shutting down completed. Exiting...')

        process.exit(error ? 1 : 0)
    }

    private setupContinuousProfiling(): void {
        if (!this.config.CONTINUOUS_PROFILING_ENABLED) {
            logger.info('Continuous profiling is disabled')
            return
        }

        if (!this.config.PYROSCOPE_SERVER_ADDRESS) {
            logger.warn('Continuous profiling is enabled but PYROSCOPE_SERVER_ADDRESS is empty, skipping')
            return
        }

        try {
            const tags = this.collectK8sTags()

            Pyroscope.init({
                serverAddress: this.config.PYROSCOPE_SERVER_ADDRESS,
                appName: this.config.PYROSCOPE_APPLICATION_NAME || 'nodejs',
                tags,
            })

            Pyroscope.start()
            logger.info('Continuous profiling started', {
                serverAddress: this.config.PYROSCOPE_SERVER_ADDRESS,
                appName: this.config.PYROSCOPE_APPLICATION_NAME || 'nodejs',
                tags,
            })
        } catch (error) {
            logger.error('Failed to start continuous profiling', { error })
        }
    }

    private collectK8sTags(): Record<string, string> {
        // K8s metadata environment variables for Pyroscope tags
        const k8sTagEnvVars: Record<string, string> = {
            namespace: 'K8S_NAMESPACE',
            pod: 'K8S_POD_NAME',
            node: 'K8S_NODE_NAME',
            pod_template_hash: 'K8S_POD_TEMPLATE_HASH',
            app_instance: 'K8S_APP_INSTANCE',
            app: 'K8S_APP',
            container: 'K8S_CONTAINER_NAME',
            controller_type: 'K8S_CONTROLLER_TYPE',
        }

        const tags: Record<string, string> = { src: 'SDK' }
        for (const [tagName, envVar] of Object.entries(k8sTagEnvVars)) {
            const value = process.env[envVar]
            if (value) {
                tags[tagName] = value
            } else {
                logger.warn(`K8s tag ${tagName} not set (env var ${envVar} is empty)`)
            }
        }
        return tags
    }
}
