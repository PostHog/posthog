import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { initializePrometheusLabels } from './api/router'
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
import { CyclotronV2JanitorService } from './cdp/services/cyclotron-v2'
import { EncryptedFields } from './cdp/utils/encryption-utils'
import { defaultConfig } from './config/config'
import { createIngestionRedisConnectionConfig, createPosthogRedisConnectionConfig } from './config/redis-pools'
import { startEvaluationScheduler } from './evaluation-scheduler/evaluation-scheduler'
import { KafkaProducerWrapper } from './kafka/producer'
import { LogsIngestionConsumer } from './logs-ingestion/logs-ingestion-consumer'
import { TracesIngestionConsumer } from './logs-ingestion/traces-ingestion-consumer'
import { CleanupResources, NodeServer, ServerLifecycle } from './servers/base-server'
import { SessionRecordingIngester } from './session-recording/consumer'
import { RecordingApi } from './session-replay/recording-api/recording-api'
import { PluginServerService, PluginsServerConfig, RedisPool } from './types'
import { ServerCommands } from './utils/commands'
import { PostgresRouter } from './utils/db/postgres'
import { createRedisPoolFromConfig } from './utils/db/redis'
import { GeoIPService } from './utils/geoip'
import { logger } from './utils/logger'
import { PubSub } from './utils/pubsub'
import { TeamManager } from './utils/team-manager'
import { GroupTypeManager } from './worker/ingestion/group-type-manager'
import { PostgresGroupRepository } from './worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from './worker/ingestion/persons/repositories/postgres-person-repository'

/**
 * PluginServer handles CDP, recordings, logs, evaluation scheduler, and local-dev combined modes.
 * Ingestion (ingestion-v2, ingestion-v2-testing) is handled by IngestionGeneralServer — see index.ts.
 */
export class PluginServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: PluginsServerConfig

    // Infrastructure resources (tracked for shutdown cleanup)
    private kafkaProducer?: KafkaProducerWrapper
    private kafkaMetricsProducer?: KafkaProducerWrapper
    private postgres?: PostgresRouter
    private redisPool?: RedisPool
    private posthogRedisPool?: RedisPool
    private pubsub?: PubSub

    constructor(config: Partial<PluginsServerConfig> = {}) {
        this.config = { ...defaultConfig, ...config }
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => this.startServices(),
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    private async startServices(): Promise<void> {
        initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)

        const capabilities = getPluginServerCapabilities(this.config)

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

        // 1. Shared infrastructure (always needed)
        const { teamManager } = await this.createSharedInfrastructure()

        // 2. Services shared by CDP (geoip, repos, encryption)
        let cdpServices: Awaited<ReturnType<typeof this.createCdpSharedServices>> | undefined
        if (needsCdp) {
            cdpServices = await this.createCdpSharedServices()
        }

        // 3. CDP + Logs + Traces services (posthog redis, quota limiting)
        let cdpLogsServices: ReturnType<typeof this.createCdpLogsServices> | undefined
        if (needsCdp || needsLogs || needsTraces) {
            cdpLogsServices = this.createCdpLogsServices(teamManager)
        }

        // Build typed deps objects for consumers
        const cdpDeps: CdpConsumerBaseDeps | undefined = needsCdp
            ? {
                  postgres: this.postgres!,
                  pubSub: this.pubsub!,
                  encryptedFields: cdpServices!.encryptedFields,
                  teamManager,
                  integrationManager: cdpServices!.integrationManager,
                  kafkaProducer: this.kafkaProducer!,
                  internalCaptureService: cdpServices!.internalCaptureService,
                  personRepository: cdpServices!.personRepository,
                  geoipService: cdpServices!.geoipService,
                  groupRepository: cdpServices!.groupRepository,
                  quotaLimiting: cdpLogsServices!.quotaLimiting,
              }
            : undefined

        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

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
                groupTypeManager: new GroupTypeManager(cdpServices!.groupRepository, teamManager),
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
                this.lifecycle.expressApp.use('/', api.router())
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
                throw new Error('CYCLOTRON_NODE_DATABASE_URL not configured but required for CyclotronV2JanitorService')
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
            this.lifecycle.expressApp.use('/', serverCommands.router())
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

        if (capabilities.cdpBatchHogFlow) {
            serviceLoaders.push(async () => {
                const consumer = new CdpBatchHogFlowRequestsConsumer(this.config, cdpDeps!)
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

        if (capabilities.recordingApi) {
            serviceLoaders.push(async () => {
                const api = new RecordingApi(this.config, this.postgres!)
                this.lifecycle.expressApp.use('/', api.router())
                await api.start()
                return api.service
            })
        }

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [this.kafkaProducer, this.kafkaMetricsProducer].filter(Boolean) as KafkaProducerWrapper[],
            redisPools: [this.redisPool, this.posthogRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
        }
    }

    // =========================================================================
    // Service initialization helpers (grouped by domain)
    // =========================================================================

    private async createSharedInfrastructure(): Promise<{ teamManager: TeamManager }> {
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
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

    private async createCdpSharedServices(): Promise<{
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
}
