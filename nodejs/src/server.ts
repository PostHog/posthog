import * as Pyroscope from '@pyroscope/nodejs'
import { Server } from 'http'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { initializePrometheusLabels, setupCommonRoutes, setupExpressApp } from './api/router'
import { getPluginServerCapabilities } from './capabilities'
import { CdpApi } from './cdp/cdp-api'
import { CdpConsumerBaseDeps } from './cdp/consumers/cdp-base.consumer'
import { CdpBatchHogFlowRequestsConsumer } from './cdp/consumers/cdp-batch-hogflow.consumer'
import { CdpCohortMembershipConsumer } from './cdp/consumers/cdp-cohort-membership.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpCyclotronWorker } from './cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpDatawarehouseEventsConsumer } from './cdp/consumers/cdp-data-warehouse-events.consumer'
import { CdpEventsConsumer } from './cdp/consumers/cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp/consumers/cdp-internal-event.consumer'
import { CdpLegacyEventsConsumer, CdpLegacyEventsConsumerDeps } from './cdp/consumers/cdp-legacy-event.consumer'
import { CdpPersonUpdatesConsumer } from './cdp/consumers/cdp-person-updates-consumer'
import { CdpPrecalculatedFiltersConsumer } from './cdp/consumers/cdp-precalculated-filters.consumer'
import {
    HogTransformerServiceDeps,
    createHogTransformerService,
} from './cdp/hog-transformations/hog-transformer.service'
import { CyclotronV2JanitorService } from './cdp/services/cyclotron-v2'
import { EncryptedFields } from './cdp/utils/encryption-utils'
import { defaultConfig } from './config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from './config/kafka-topics'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
    createPosthogRedisConnectionConfig,
} from './config/redis-pools'
import { startEvaluationScheduler } from './evaluation-scheduler/evaluation-scheduler'
import { CookielessManager } from './ingestion/cookieless/cookieless-manager'
import { IngestionConsumer, IngestionConsumerDeps } from './ingestion/ingestion-consumer'
import { IngestionTestingConsumer } from './ingestion/ingestion-testing-consumer'
import { KafkaProducerWrapper } from './kafka/producer'
import { onShutdown } from './lifecycle'
import { LogsIngestionConsumer } from './logs-ingestion/logs-ingestion-consumer'
import { TracesIngestionConsumer } from './logs-ingestion/traces-ingestion-consumer'
import { SessionRecordingIngester } from './session-recording/consumer'
import { RecordingApi } from './session-replay/recording-api/recording-api'
import { PluginServerService, PluginsServerConfig, RedisPool } from './types'
import { ServerCommands } from './utils/commands'
import { PostgresRouter } from './utils/db/postgres'
import { createRedisPoolFromConfig } from './utils/db/redis'
import { isTestEnv } from './utils/env-utils'
import { GeoIPService } from './utils/geoip'
import { logger } from './utils/logger'
import { NodeInstrumentation } from './utils/node-instrumentation'
import { captureException, shutdown as posthogShutdown } from './utils/posthog'
import { PubSub } from './utils/pubsub'
import { TeamManager } from './utils/team-manager'
import { delay } from './utils/utils'
import { GroupTypeManager } from './worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from './worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from './worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from './worker/ingestion/persons/repositories/postgres-person-repository'

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
    expressApp: express.Application
    nodeInstrumentation: NodeInstrumentation
    private podTerminationTimer?: NodeJS.Timeout
    private processListeners: Map<string, (...args: any[]) => void> = new Map()

    // Infrastructure resources (tracked for shutdown cleanup)
    private kafkaProducer?: KafkaProducerWrapper
    private kafkaMetricsProducer?: KafkaProducerWrapper
    private postgres?: PostgresRouter
    private redisPool?: RedisPool
    private posthogRedisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager

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

        this.expressApp = setupExpressApp({ internalApiSecret: this.config.INTERNAL_API_SECRET })
        this.nodeInstrumentation = new NodeInstrumentation(this.config.INSTRUMENT_THREAD_PERFORMANCE)
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
        initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)

        const capabilities = getPluginServerCapabilities(this.config)

        const needsIngestion = !!(capabilities.ingestionV2Combined || capabilities.ingestionV2)

        const needsCdp = !!(
            capabilities.cdpProcessedEvents ||
            capabilities.cdpDataWarehouseEvents ||
            capabilities.cdpInternalEvents ||
            capabilities.cdpPersonUpdates ||
            capabilities.cdpLegacyOnEvent ||
            capabilities.cdpApi ||
            capabilities.cdpCyclotronWorker ||
            capabilities.cdpCyclotronWorkerHogFlow ||
            capabilities.cdpPrecalculatedFilters ||
            capabilities.cdpCohortMembership ||
            capabilities.cdpBatchHogFlow
        )
        const needsLogs = !!capabilities.logsIngestion
        const needsTraces = !!capabilities.tracesIngestion

        try {
            // 1. Shared infrastructure (always needed)
            const { teamManager } = await this.createSharedInfrastructure()

            // 2. Services shared by ingestion + CDP (geoip, repos, encryption)
            let ingestionCdpServices: Awaited<ReturnType<typeof this.createIngestionCdpServices>> | undefined
            if (needsIngestion || needsCdp) {
                ingestionCdpServices = await this.createIngestionCdpServices()
            }

            // 3. Ingestion-specific services (cookieless, group type, clickhouse groups)
            let ingestionServices: ReturnType<typeof this.createIngestionServices> | undefined
            if (needsIngestion) {
                ingestionServices = this.createIngestionServices(teamManager, ingestionCdpServices!.groupRepository)
            }

            // 4. CDP + Logs services (posthog redis, quota limiting)
            let cdpLogsServices: ReturnType<typeof this.createCdpLogsServices> | undefined
            if (needsCdp || needsLogs || needsTraces) {
                cdpLogsServices = this.createCdpLogsServices(teamManager)
            }

            // Build typed deps objects for consumers
            const cdpDeps: CdpConsumerBaseDeps | undefined = needsCdp
                ? {
                      postgres: this.postgres!,
                      pubSub: this.pubsub!,
                      encryptedFields: ingestionCdpServices!.encryptedFields,
                      teamManager,
                      integrationManager: ingestionCdpServices!.integrationManager,
                      kafkaProducer: this.kafkaProducer!,
                      internalCaptureService: ingestionCdpServices!.internalCaptureService,
                      personRepository: ingestionCdpServices!.personRepository,
                      geoipService: ingestionCdpServices!.geoipService,
                      groupRepository: ingestionCdpServices!.groupRepository,
                      quotaLimiting: cdpLogsServices!.quotaLimiting,
                  }
                : undefined

            const hogTransformerDeps: HogTransformerServiceDeps | undefined = needsIngestion
                ? {
                      geoipService: ingestionCdpServices!.geoipService,
                      postgres: this.postgres!,
                      pubSub: this.pubsub!,
                      encryptedFields: ingestionCdpServices!.encryptedFields,
                      integrationManager: ingestionCdpServices!.integrationManager,
                      kafkaProducer: this.kafkaMetricsProducer!,
                      teamManager,
                      internalCaptureService: ingestionCdpServices!.internalCaptureService,
                  }
                : undefined

            const serviceLoaders: (() => Promise<PluginServerService>)[] = []

            if (capabilities.ingestionV2Combined) {
                // NOTE: This is for single process deployments like local dev and hobby - it runs all possible consumers
                // in a single process. In production these are each separate Deployments of the standard ingestion consumer
                const ingestionDeps: IngestionConsumerDeps = {
                    postgres: this.postgres!,
                    redisPool: this.redisPool!,
                    kafkaProducer: this.kafkaProducer!,
                    kafkaMetricsProducer: this.kafkaMetricsProducer!,
                    teamManager,
                    groupTypeManager: ingestionServices!.groupTypeManager,
                    groupRepository: ingestionCdpServices!.groupRepository,
                    clickhouseGroupRepository: ingestionServices!.clickhouseGroupRepository,
                    personRepository: ingestionCdpServices!.personRepository,
                    cookielessManager: this.cookielessManager!,
                    hogTransformer: createHogTransformerService(this.config, hogTransformerDeps!),
                }

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
                        const consumer = new IngestionConsumer(this.config, ingestionDeps, {
                            INGESTION_CONSUMER_CONSUME_TOPIC: consumerOption.topic,
                            INGESTION_CONSUMER_GROUP_ID: consumerOption.group_id,
                        })
                        await consumer.start()
                        return consumer.service
                    })
                }
            } else if (capabilities.ingestionV2) {
                const ingestionDeps: IngestionConsumerDeps = {
                    postgres: this.postgres!,
                    redisPool: this.redisPool!,
                    kafkaProducer: this.kafkaProducer!,
                    kafkaMetricsProducer: this.kafkaMetricsProducer!,
                    teamManager,
                    groupTypeManager: ingestionServices!.groupTypeManager,
                    groupRepository: ingestionCdpServices!.groupRepository,
                    clickhouseGroupRepository: ingestionServices!.clickhouseGroupRepository,
                    personRepository: ingestionCdpServices!.personRepository,
                    cookielessManager: this.cookielessManager!,
                    hogTransformer: createHogTransformerService(this.config, hogTransformerDeps!),
                }

                serviceLoaders.push(async () => {
                    const consumer = new IngestionConsumer(this.config, ingestionDeps)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.ingestionV2Testing) {
                serviceLoaders.push(async () => {
                    // All output (events, overflow, DLQ) writes to WarpStream
                    const kafkaWarpStreamProducer = await KafkaProducerWrapper.create(
                        this.config.KAFKA_CLIENT_RACK,
                        'WARPSTREAM_PRODUCER'
                    )

                    const consumer = new IngestionTestingConsumer(this.config, {
                        kafkaProducer: kafkaWarpStreamProducer,
                        teamManager,
                    })
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.evaluationScheduler) {
                serviceLoaders.push(() =>
                    startEvaluationScheduler(this.config, {
                        postgres: this.postgres!,
                        pubSub: this.pubsub!,
                    })
                )
            }

            if (capabilities.sessionRecordingBlobIngestionV2) {
                serviceLoaders.push(async () => {
                    const kafkaMessageProducer = await KafkaProducerWrapper.create(
                        this.config.KAFKA_CLIENT_RACK,
                        'WARPSTREAM_PRODUCER'
                    )

                    const ingester = new SessionRecordingIngester(
                        this.config,
                        false,
                        this.postgres!,
                        this.kafkaProducer!,
                        kafkaMessageProducer
                    )
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.sessionRecordingBlobIngestionV2Overflow) {
                serviceLoaders.push(async () => {
                    const kafkaMessageProducer = await KafkaProducerWrapper.create(
                        this.config.KAFKA_CLIENT_RACK,
                        'WARPSTREAM_PRODUCER'
                    )

                    const ingester = new SessionRecordingIngester(
                        this.config,
                        true,
                        this.postgres!,
                        this.kafkaProducer!,
                        kafkaMessageProducer
                    )
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.cdpProcessedEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpEventsConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpDataWarehouseEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpDatawarehouseEventsConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpInternalEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpInternalEventsConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpPersonUpdates) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpPersonUpdatesConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpLegacyOnEvent) {
                const legacyDeps: CdpLegacyEventsConsumerDeps = {
                    ...cdpDeps!,
                    groupTypeManager: new GroupTypeManager(ingestionCdpServices!.groupRepository, teamManager),
                }
                serviceLoaders.push(async () => {
                    const consumer = new CdpLegacyEventsConsumer(this.config, legacyDeps)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpApi) {
                serviceLoaders.push(async () => {
                    const api = new CdpApi(this.config, cdpDeps!)
                    this.expressApp.use('/', api.router())
                    await api.start()
                    return api.service
                })
            }

            if (capabilities.cdpCyclotronWorker) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorker(this.config, cdpDeps!)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCyclotronV2Janitor) {
                if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
                    throw new Error(
                        'CYCLOTRON_NODE_DATABASE_URL not configured but required for CyclotronV2JanitorService'
                    )
                }
                serviceLoaders.push(async () => {
                    const janitor = new CyclotronV2JanitorService({
                        pool: {
                            dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL!,
                            maxConnections: this.config.CYCLOTRON_NODE_MAX_CONNECTIONS,
                            idleTimeoutMs: this.config.CYCLOTRON_NODE_IDLE_TIMEOUT_MS,
                        },
                        cleanupBatchSize: this.config.CYCLOTRON_NODE_JANITOR_CLEANUP_BATCH_SIZE,
                        cleanupIntervalMs: this.config.CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS,
                        stallTimeoutMs: this.config.CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS,
                        maxTouchCount: this.config.CYCLOTRON_NODE_JANITOR_MAX_TOUCH_COUNT,
                        cleanupGraceMs: this.config.CYCLOTRON_NODE_JANITOR_CLEANUP_GRACE_MS,
                    })
                    await janitor.start()
                    return janitor.service
                })
            }

            if (capabilities.cdpCyclotronWorkerHogFlow) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorkerHogFlow(this.config, cdpDeps!)
                    await worker.start()
                    return worker.service
                })
            }

            // ServerCommands is always created
            serviceLoaders.push(() => {
                const serverCommands = new ServerCommands(this.pubsub!)
                this.expressApp.use('/', serverCommands.router())
                return Promise.resolve(serverCommands.service)
            })

            if (capabilities.cdpPrecalculatedFilters) {
                serviceLoaders.push(async () => {
                    const worker = new CdpPrecalculatedFiltersConsumer(this.config, cdpDeps!)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCohortMembership) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpCohortMembershipConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.logsIngestion) {
                serviceLoaders.push(async () => {
                    const consumer = new LogsIngestionConsumer(this.config, {
                        teamManager,
                        quotaLimiting: cdpLogsServices!.quotaLimiting,
                    })
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.tracesIngestion) {
                serviceLoaders.push(async () => {
                    const consumer = new TracesIngestionConsumer(this.config, {
                        teamManager,
                        quotaLimiting: cdpLogsServices!.quotaLimiting,
                    })
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpBatchHogFlow) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpBatchHogFlowRequestsConsumer(this.config, cdpDeps!)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.recordingApi) {
                serviceLoaders.push(async () => {
                    const api = new RecordingApi(this.config, this.postgres!)
                    this.expressApp.use('/', api.router())
                    await api.start()
                    return api.service
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

    // =========================================================================
    // Service initialization helpers (grouped by domain)
    // =========================================================================

    private async createSharedInfrastructure(): Promise<{ teamManager: TeamManager }> {
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        this.kafkaMetricsProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        logger.info('👍', 'Kafka ready')

        logger.info('🤔', 'Connecting to ingestion Redis...')
        this.redisPool = createRedisPoolFromConfig({
            connection: createIngestionRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'Ingestion Redis ready')

        this.pubsub = new PubSub(this.redisPool)
        await this.pubsub.start()

        const teamManager = new TeamManager(this.postgres)

        return { teamManager }
    }

    private async createIngestionCdpServices(): Promise<{
        geoipService: GeoIPService
        personRepository: PostgresPersonRepository
        groupRepository: PostgresGroupRepository
        encryptedFields: EncryptedFields
        integrationManager: IntegrationManagerService
        internalCaptureService: InternalCaptureService
    }> {
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personRepository = new PostgresPersonRepository(this.postgres!, {
            calculatePropertiesSize: this.config.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
        })
        const groupRepository = new PostgresGroupRepository(this.postgres!)
        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub!, this.postgres!, encryptedFields)
        const internalCaptureService = new InternalCaptureService(this.config)

        return {
            geoipService,
            personRepository,
            groupRepository,
            encryptedFields,
            integrationManager,
            internalCaptureService,
        }
    }

    private createIngestionServices(
        teamManager: TeamManager,
        groupRepository: PostgresGroupRepository
    ): {
        groupTypeManager: GroupTypeManager
        clickhouseGroupRepository: ClickhouseGroupRepository
    } {
        logger.info('🤔', 'Connecting to cookieless Redis...')
        this.cookielessRedisPool = createRedisPoolFromConfig({
            connection: createCookielessRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'Cookieless Redis ready')

        this.cookielessManager = new CookielessManager(this.config, this.cookielessRedisPool)
        const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)
        const clickhouseGroupRepository = new ClickhouseGroupRepository(this.kafkaProducer!)

        return { groupTypeManager, clickhouseGroupRepository }
    }

    private createCdpLogsServices(teamManager: TeamManager): { quotaLimiting: QuotaLimiting } {
        logger.info('🤔', 'Connecting to PostHog Redis...')
        this.posthogRedisPool = createRedisPoolFromConfig({
            connection: createPosthogRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'PostHog Redis ready')

        const quotaLimiting = new QuotaLimiting(this.posthogRedisPool, teamManager)

        return { quotaLimiting }
    }

    // =========================================================================
    // Lifecycle
    // =========================================================================

    private setupListeners(): void {
        for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
            const handler = async () => {
                // This makes async exit possible with the process waiting until jobs are closed
                logger.info('👋', `process handling ${signal} event. Stopping...`)
                await this.stop()
            }
            this.processListeners.set(signal, handler)
            process.on(signal, handler)
        }

        const rejectionHandler = (error: Error | any) => {
            logger.error('🤮', `Unhandled Promise Rejection`, { error: String(error) })

            captureException(error, {
                extra: { detected_at: `pluginServer.ts on unhandledRejection` },
            })

            void this.stop(error)
        }
        this.processListeners.set('unhandledRejection', rejectionHandler)
        process.on('unhandledRejection', rejectionHandler)

        const exceptionHandler = async (error: Error) => {
            await this.stop(error)
        }
        this.processListeners.set('uncaughtException', exceptionHandler)
        process.on('uncaughtException', exceptionHandler)
    }

    async stop(error?: Error): Promise<void> {
        // Remove process listeners to prevent accumulation across test runs
        for (const [event, handler] of this.processListeners) {
            process.removeListener(event, handler)
        }
        this.processListeners.clear()

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

        if (this.kafkaProducer) {
            logger.info('💤', ' Shutting down kafka producer...')
            // Wait 2 seconds to flush the last queues and caches
            await Promise.all([this.kafkaProducer.flush(), delay(2000)])
        }

        logger.info('💤', ' Shutting down infrastructure...')
        await Promise.allSettled([
            this.kafkaProducer?.disconnect(),
            this.kafkaMetricsProducer?.disconnect(),
            this.redisPool?.drain(),
            this.posthogRedisPool?.drain(),
            this.cookielessRedisPool?.drain(),
            this.postgres?.end(),
        ])
        await this.redisPool?.clear()
        await this.posthogRedisPool?.clear()
        await this.cookielessRedisPool?.clear()
        this.cookielessManager?.shutdown()

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
