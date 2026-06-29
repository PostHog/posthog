import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import { createIngestionRedisConnectionConfig, createPosthogRedisConnectionConfig } from '~/common/config/redis-pools'
import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { createPersonHogClient } from '~/common/personhog'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { ServerCommands } from '~/common/utils/commands'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { GeoIPService } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'

import { startEvaluationScheduler } from './ai-observability/evaluation-scheduler/evaluation-scheduler'
import { getPluginServerCapabilities } from './capabilities'
import { CdpApi } from './cdp/cdp-api'
import { CdpConsumerBaseDeps } from './cdp/consumers/cdp-base.consumer'
import { CdpBatchHogFlowRequestsConsumer } from './cdp/consumers/cdp-batch-hogflow.consumer'
import { CdpCohortMembershipConsumer } from './cdp/consumers/cdp-cohort-membership.consumer'
import { CdpCyclotronWorkerBatchResolve } from './cdp/consumers/cdp-cyclotron-worker-batch-resolve.consumer'
import { CdpCyclotronWorkerEmail } from './cdp/consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpCyclotronWorker } from './cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpDatawarehouseEventsConsumer } from './cdp/consumers/cdp-data-warehouse-events.consumer'
import { CdpEventsConsumer } from './cdp/consumers/cdp-events.consumer'
import { CdpHogflowSubscriptionMatcherConsumer } from './cdp/consumers/cdp-hogflow-subscription-matcher.consumer'
import { CdpInternalEventsConsumer } from './cdp/consumers/cdp-internal-event.consumer'
import { CdpLegacyEventsConsumer } from './cdp/consumers/cdp-legacy-event.consumer'
import { CdpPersonUpdatesConsumer } from './cdp/consumers/cdp-person-updates-consumer'
import { CdpPrecalculatedFiltersConsumer } from './cdp/consumers/cdp-precalculated-filters.consumer'
import { CdpRerunWorkerConsumer } from './cdp/consumers/cdp-rerun-worker.consumer'
import { createCdpProducerRegistry } from './cdp/outputs/producer-registry'
import { CdpProducerName } from './cdp/outputs/producers'
import { CyclotronV2JanitorService, CyclotronV2Manager, CyclotronV2Worker } from './cdp/services/cyclotron-v2'
import { HogFlowScheduleService } from './cdp/services/hogflow-schedule/hogflow-schedule.service'
import { HOGFLOW_BATCH_RESOLVE_QUEUE } from './cdp/services/hogflows/batch-resolver.types'
import { HogFlowBatchPersonQueryService } from './cdp/services/hogflows/hogflow-batch-person-query.service'
import { CyclotronJobQueueKafka } from './cdp/services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgres } from './cdp/services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from './cdp/services/job-queue/job-queue-postgres-v2'
import { CyclotronJobQueueRateLimitedPostgresV2 } from './cdp/services/job-queue/job-queue-rate-limited-postgres-v2'
import { createSesRateLimiterValkeyPool } from './cdp/services/rate-limiter/rate-limiter-valkey-pool'
import { RateLimiterService } from './cdp/services/rate-limiter/rate-limiter.service'
import { EncryptedFields } from './cdp/utils/encryption-utils'
import { CleanupResources, NodeServer, ServerLifecycle } from './servers/base-server'
import { PluginServerService, PluginsServerConfig, RedisPool } from './types'

/**
 * PluginServer handles CDP, logs, evaluation scheduler, and local-dev combined modes.
 * Ingestion is handled by IngestionGeneralServer, recordings by IngestionSessionRerunServer — see index.ts.
 */
export class PluginServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: PluginsServerConfig

    // Infrastructure resources (tracked for shutdown cleanup)
    private cdpProducerRegistry?: KafkaProducerRegistry<CdpProducerName>
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
        initializePrometheusLabels()

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
            capabilities.cdpCyclotronWorkerHogFlowLegacyPg ||
            capabilities.cdpCyclotronWorkerEmail ||
            capabilities.cdpCyclotronWorkerEmailLegacyPg ||
            capabilities.cdpPrecalculatedFilters ||
            capabilities.cdpCohortMembership ||
            capabilities.cdpBatchHogFlow ||
            capabilities.cdpCyclotronWorkerBatchResolve ||
            capabilities.cdpHogflowSubscriptionMatcher ||
            capabilities.cdpRerunWorker
        )
        // 1. Shared infrastructure (always needed)
        const { teamManager } = await this.createSharedInfrastructure()

        // 2. Services shared by CDP (geoip, repos, encryption)
        let cdpServices: Awaited<ReturnType<typeof this.createCdpSharedServices>> | undefined
        if (needsCdp) {
            this.cdpProducerRegistry = await createCdpProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
            cdpServices = await this.createCdpSharedServices()
        }

        // 3. CDP services (posthog redis, quota limiting)
        let cdpQuotaServices: ReturnType<typeof this.createCdpQuotaServices> | undefined
        if (needsCdp) {
            cdpQuotaServices = this.createCdpQuotaServices(teamManager)
        }

        // Build typed deps objects for consumers
        const cdpDeps: CdpConsumerBaseDeps | undefined = needsCdp
            ? {
                  postgres: this.postgres!,
                  pubSub: this.pubsub!,
                  encryptedFields: cdpServices!.encryptedFields,
                  teamManager,
                  integrationManager: cdpServices!.integrationManager,
                  cdpProducerRegistry: this.cdpProducerRegistry!,
                  internalCaptureService: cdpServices!.internalCaptureService,
                  personRepository: cdpServices!.personRepository,
                  geoipService: cdpServices!.geoipService,
                  groupRepository: cdpServices!.groupRepository,
                  quotaLimiting: cdpQuotaServices!.quotaLimiting,
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

        // Create shared job queue backends — each consumer gets the one(s) it needs
        const kafkaQueue = new CyclotronJobQueueKafka(
            this.config.KAFKA_CLIENT_RACK,
            this.config,
            this.config.CONSUMER_BATCH_SIZE
        )
        const postgresV2Queue = new CyclotronJobQueuePostgresV2(this.config.CONSUMER_BATCH_SIZE, this.config)

        if (capabilities.cdpProcessedEvents) {
            serviceLoaders.push(async () => {
                const consumer = new CdpEventsConsumer(this.config, cdpDeps!, {
                    hogQueue: kafkaQueue,
                    hogflowQueue: postgresV2Queue,
                })
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpDataWarehouseEvents) {
            serviceLoaders.push(async () => {
                const consumer = new CdpDatawarehouseEventsConsumer(this.config, cdpDeps!, {
                    hogQueue: kafkaQueue,
                    hogflowQueue: postgresV2Queue,
                })
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpInternalEvents) {
            serviceLoaders.push(async () => {
                const consumer = new CdpInternalEventsConsumer(this.config, cdpDeps!, kafkaQueue)
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpPersonUpdates) {
            serviceLoaders.push(async () => {
                const consumer = new CdpPersonUpdatesConsumer(this.config, cdpDeps!, kafkaQueue)
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpLegacyOnEvent) {
            serviceLoaders.push(async () => {
                const consumer = new CdpLegacyEventsConsumer(this.config, cdpDeps!)
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpApi) {
            serviceLoaders.push(async () => {
                // Only wire a batch-resolver producer when the cyclotron-node DB
                // is configured; otherwise leave it null (flag-off path uses
                // Kafka and doesn't need a producer).
                const batchResolverProducer = this.config.CYCLOTRON_NODE_DATABASE_URL
                    ? new CyclotronV2Manager({
                          pool: { dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL, maxConnections: 5 },
                      })
                    : null
                const api = new CdpApi(
                    this.config,
                    cdpDeps!,
                    { hogQueue: kafkaQueue, hogflowQueue: postgresV2Queue },
                    batchResolverProducer
                )
                this.lifecycle.expressApp.use('/', api.router())
                await api.start()
                return api.service
            })
        }

        if (capabilities.cdpCyclotronWorker) {
            serviceLoaders.push(async () => {
                const worker = new CdpCyclotronWorker(this.config, cdpDeps!, kafkaQueue)
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
                // Dedicated queue instance per consumer worker — sharing one
                // CyclotronJobQueuePostgresV2 across two consumers (hogflow + email)
                // collides on `this.worker`, `pendingJobs`, and the pg pool. In
                // prod each capability runs in its own pod so they get fresh
                // instances naturally; locally we'd silently double-process when
                // both capabilities are enabled in the same process.
                const queue = new CyclotronJobQueuePostgresV2(this.config.CONSUMER_BATCH_SIZE, this.config)
                const worker = new CdpCyclotronWorkerHogFlow(this.config, cdpDeps!, queue)
                await worker.start()
                return worker.service
            })
        }

        if (capabilities.cdpRerunWorker) {
            serviceLoaders.push(async () => {
                const worker = new CdpRerunWorkerConsumer(this.config, cdpDeps!, {
                    hog_function: kafkaQueue,
                    hog_flow: postgresV2Queue,
                })
                await worker.start()
                return worker.service
            })
        }

        // Legacy postgres v1 drain for hogflow jobs — delete once cdp-cyclotron-worker-hogflows-pg-legacy is shut down
        if (capabilities.cdpCyclotronWorkerHogFlowLegacyPg) {
            serviceLoaders.push(async () => {
                const legacyQueue = new CyclotronJobQueuePostgres(this.config.CONSUMER_BATCH_SIZE, this.config)
                const worker = new CdpCyclotronWorkerHogFlow(this.config, cdpDeps!, legacyQueue)
                await worker.start()
                return worker.service
            })
        }

        // Transitional drain for email jobs stranded on the legacy V1 queue — the email worker
        // run against V1, sending inline. Delete once V1 'email' throughput is ~0.
        if (capabilities.cdpCyclotronWorkerEmailLegacyPg) {
            serviceLoaders.push(async () => {
                const legacyQueue = new CyclotronJobQueuePostgres(this.config.CONSUMER_BATCH_SIZE, this.config)
                const worker = new CdpCyclotronWorkerEmail(this.config, cdpDeps!, legacyQueue)
                await worker.start()
                return worker.service
            })
        }

        if (capabilities.cdpCyclotronWorkerEmail) {
            serviceLoaders.push(async () => {
                // Dedicated queue instance — see note on cdpCyclotronWorkerHogFlow above.
                // When the SES rate-limiter Valkey is configured, use the rate-limited
                // variant so dequeue is gated by a Valkey-backed token bucket. Without
                // the env var (typical for local dev outside k8s) we fall back to the
                // plain queue and dequeue is unthrottled.
                //
                // Fair dequeue (per-team round-robin) is intrinsic to the email queue —
                // the worker derives it from its queue name — and applies regardless of
                // whether rate limiting is on.
                const sesValkey = createSesRateLimiterValkeyPool(this.config)
                const queue = sesValkey
                    ? new CyclotronJobQueueRateLimitedPostgresV2(this.config.CONSUMER_BATCH_SIZE, this.config, {
                          limiter: new RateLimiterService(sesValkey, { name: 'ses' }),
                          key: '@posthog/ses/global',
                          capacity: this.config.CDP_SES_RATE_LIMIT_CAPACITY,
                          refillPerSecond: this.config.CDP_SES_RATE_LIMIT_REFILL_PER_SECOND,
                          throttledPollDelayMs: this.config.CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS,
                      })
                    : new CyclotronJobQueuePostgresV2(this.config.CONSUMER_BATCH_SIZE, this.config)
                const worker = new CdpCyclotronWorkerEmail(this.config, cdpDeps!, queue)
                await worker.start()
                return worker.service
            })
        }

        if (capabilities.cdpHogflowScheduler) {
            serviceLoaders.push(() => {
                const scheduler = new HogFlowScheduleService(this.config)
                scheduler.start()
                return Promise.resolve(scheduler.service)
            })
        }

        // ServerCommands is always created
        serviceLoaders.push(() => {
            const serverCommands = new ServerCommands(this.pubsub!)
            this.lifecycle.expressApp.use('/', serverCommands.router())
            return Promise.resolve(serverCommands.service)
        })

        if (capabilities.cdpBatchHogFlow) {
            serviceLoaders.push(async () => {
                const consumer = new CdpBatchHogFlowRequestsConsumer(this.config, cdpDeps!, postgresV2Queue)
                await consumer.start()
                return consumer.service
            })
        }

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

        if (capabilities.cdpBatchHogFlow) {
            serviceLoaders.push(async () => {
                const consumer = new CdpBatchHogFlowRequestsConsumer(this.config, cdpDeps!, postgresV2Queue)
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpHogflowSubscriptionMatcher) {
            serviceLoaders.push(async () => {
                const consumer = new CdpHogflowSubscriptionMatcherConsumer(this.config, cdpDeps!)
                await consumer.start()
                return consumer.service
            })
        }

        if (capabilities.cdpCyclotronWorkerBatchResolve) {
            serviceLoaders.push(async () => {
                if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
                    throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for CdpCyclotronWorkerBatchResolve')
                }
                const cyclotronWorker = new CyclotronV2Worker({
                    pool: {
                        dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL,
                        maxConnections: 10,
                    },
                    queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
                    pollDelayMs: 100,
                })
                const internalFetchService = new InternalFetchService(
                    this.config.INTERNAL_API_BASE_URL,
                    this.config.INTERNAL_API_SECRET
                )
                const hogFlowBatchPersonQueryService = new HogFlowBatchPersonQueryService(internalFetchService)
                const consumer = new CdpCyclotronWorkerBatchResolve(
                    this.config,
                    cdpDeps!,
                    cyclotronWorker,
                    hogFlowBatchPersonQueryService,
                    internalFetchService
                )
                await consumer.start()
                return consumer.service
            })
        }

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.posthogRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                await this.cdpProducerRegistry?.disconnectAll()
            },
        }
    }

    // =========================================================================
    // Service initialization helpers (grouped by domain)
    // =========================================================================

    private async createSharedInfrastructure(): Promise<{ teamManager: TeamManager }> {
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

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
        personRepository: PersonReadRepository
        groupRepository: GroupReadRepository
        encryptedFields: EncryptedFields
        integrationManager: IntegrationManagerService
        internalCaptureService: InternalCaptureService
    }> {
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personhogClient = createPersonHogClient(this.config)
        const clientLabel = this.config.PLUGIN_SERVER_MODE ?? 'unknown'

        if (!personhogClient) {
            throw new Error('PersonHog client is required for CDP — set PERSONHOG_ENABLED=true and PERSONHOG_ADDR')
        }

        const personRepository = new PersonHogPersonReadRepository(personhogClient, clientLabel)
        const groupRepository = new PersonHogGroupReadRepository(personhogClient, clientLabel)

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

    private createCdpQuotaServices(teamManager: TeamManager): { quotaLimiting: QuotaLimiting } {
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
