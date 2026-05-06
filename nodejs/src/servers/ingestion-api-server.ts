import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'

import { initializePrometheusLabels } from '../api/router'
import {
    HogTransformerService,
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import { createCookielessRedisConnectionConfig, createIngestionRedisConnectionConfig } from '../config/redis-pools'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineDeps,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from '../ingestion/analytics/joined-ingestion-pipeline'
import { createOutputsRegistry } from '../ingestion/analytics/outputs/registry'
import { deserializeKafkaMessage } from '../ingestion/api/kafka-message-converter'
import { IngestBatchRequest, IngestBatchResponse } from '../ingestion/api/types'
import {
    KafkaIngestionProducerEnvConfig,
    KafkaProducerEnvConfig,
    KafkaWarpstreamProducerEnvConfig,
    getDefaultKafkaIngestionProducerEnvConfig,
    getDefaultKafkaProducerEnvConfig,
    getDefaultKafkaWarpstreamProducerEnvConfig,
} from '../ingestion/common/config'
import { EventFilterManager } from '../ingestion/common/event-filters'
import { ProducerName } from '../ingestion/common/outputs'
import { createProducerRegistry } from '../ingestion/common/outputs/registry'
import {
    DatabaseConnectionConfig,
    IngestionConsumerConfig,
    IngestionOutputsConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    PersonHogConfig,
    RedisConnectionsConfig,
    getDefaultIngestionOutputsConfig,
} from '../ingestion/config'
import { CookielessManager } from '../ingestion/cookieless/cookieless-manager'
import { parseSplitAiEventsConfig } from '../ingestion/event-processing/split-ai-events-step'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../ingestion/personhog'
import { createOkContext } from '../ingestion/pipelines/helpers'
import { TopHog } from '../ingestion/tophog'
import { MainLaneOverflowRedirect } from '../ingestion/utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '../ingestion/utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '../ingestion/utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '../ingestion/utils/overflow-redirect/overflow-redis-repository'
import { HealthCheckResultOk, PluginServerService, RedisPool } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../utils/event-schema-enforcement-manager'
import { GeoIPService } from '../utils/geoip'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { PubSub } from '../utils/pubsub'
import { TeamManager } from '../utils/team-manager'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { ClickhouseGroupRepository } from '../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from '../worker/ingestion/groups/repositories/postgres-group-repository'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { PersonsStore } from '../worker/ingestion/persons/persons-store'
import { PostgresPersonRepository } from '../worker/ingestion/persons/repositories/postgres-person-repository'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

export type IngestionApiServerConfig = BaseServerConfig &
    IngestionConsumerConfig &
    IngestionOutputsConfig &
    HogTransformerServiceConfig &
    KafkaProducerEnvConfig &
    KafkaWarpstreamProducerEnvConfig &
    KafkaIngestionProducerEnvConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    KafkaConsumerBaseConfig &
    PersonHogConfig &
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'MMDB_FILE_LOCATION'
        | 'CAPTURE_INTERNAL_URL'
        | 'LAZY_LOADER_DEFAULT_BUFFER_MS'
        | 'LAZY_LOADER_MAX_SIZE'
        | 'TASK_TIMEOUT'
        | 'POSTHOG_API_KEY'
        | 'POSTHOG_HOST_URL'
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'KAFKA_HEALTHCHECK_SECONDS'
    >

const batchesProcessed = new Counter({
    name: 'ingestion_api_batches_processed_total',
    help: 'Total number of batches processed by the ingestion API',
})

const batchProcessingDuration = new Histogram({
    name: 'ingestion_api_batch_processing_duration_ms',
    help: 'Duration of batch processing in milliseconds',
    buckets: [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

const messagesProcessed = new Counter({
    name: 'ingestion_api_messages_processed_total',
    help: 'Total number of messages processed by the ingestion API',
})

const batchErrors = new Counter({
    name: 'ingestion_api_batch_errors_total',
    help: 'Total number of batch processing errors',
})

/**
 * Ingestion API server that exposes the ingestion pipeline as an HTTP endpoint.
 *
 * Used as a sidecar alongside a Rust Kafka consumer — the consumer reads from
 * Kafka, routes messages by distinct_id, and dispatches sub-batches to this
 * server via POST /ingest.
 *
 * Infrastructure setup mirrors IngestionGeneralServer. The difference is that
 * instead of subscribing to Kafka, this server accepts batches over HTTP.
 */
export class IngestionApiServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionApiServerConfig

    private postgres?: PostgresRouter
    private ingestionProducerRegistry?: KafkaProducerRegistry<ProducerName>
    private redisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub

    private joinedPipeline!: ReturnType<
        typeof createJoinedIngestionPipeline<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>
    >
    private promiseScheduler = new PromiseScheduler()
    private hogTransformer!: HogTransformerService
    private topHog!: TopHog

    constructor(config: Partial<IngestionApiServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultKafkaProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaIngestionProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultIngestionOutputsConfig()),
            ...config,
        }
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

        // 1. Shared infrastructure
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE!)
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

        // 2. Ingestion + CDP shared services (geoip, repos, encryption)
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personhogClient = createPersonHogClient(this.config)
        const clientLabel = this.config.PLUGIN_SERVER_MODE ?? 'unknown'

        const postgresPersonRepository = new PostgresPersonRepository(this.postgres, {
            calculatePropertiesSize: this.config.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
        })
        const personRepository = buildPersonRepository(
            personhogClient,
            postgresPersonRepository,
            this.config.PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE,
            this.config.PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS,
            clientLabel
        )
        const postgresGroupRepository = new PostgresGroupRepository(this.postgres)

        const groupRepository = buildGroupRepository(
            personhogClient,
            postgresGroupRepository,
            this.config.PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE,
            this.config.PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS,
            clientLabel
        )

        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub, this.postgres, encryptedFields)

        // 3. Ingestion-specific services
        logger.info('🤔', 'Connecting to cookieless Redis...')
        this.cookielessRedisPool = createRedisPoolFromConfig({
            connection: createCookielessRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'Cookieless Redis ready')

        this.cookielessManager = new CookielessManager(this.config, this.cookielessRedisPool)
        const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)

        // 4. Kafka producers for pipeline outputs (not consuming from Kafka)
        this.ingestionProducerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const ingestionOutputs = createOutputsRegistry().build(this.ingestionProducerRegistry, this.config)
        const clickhouseGroupRepository = new ClickhouseGroupRepository(ingestionOutputs)

        const topicFailures = await ingestionOutputs.checkTopics()
        if (topicFailures.length > 0) {
            throw new Error(`Output topic verification failed for: ${topicFailures.join(', ')}`)
        }

        // 5. HogTransformer
        const hogTransformerDeps: HogTransformerServiceDeps = {
            geoipService,
            postgres: this.postgres,
            pubSub: this.pubsub,
            encryptedFields,
            integrationManager,
            monitoringOutputs: ingestionOutputs,
            teamManager,
        }
        this.hogTransformer = createHogTransformerService(this.config, hogTransformerDeps)
        await this.hogTransformer.start()

        // 6. Pipeline dependencies
        const overflowRedisRepository = new RedisOverflowRepository({
            redisPool: this.redisPool,
            redisTTLSeconds: this.config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
        })

        let overflowRedirectService: OverflowRedirectService | undefined
        if (this.overflowEnabled()) {
            overflowRedirectService = new MainLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                localCacheTTLSeconds: this.config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                bucketCapacity: this.config.EVENT_OVERFLOW_BUCKET_CAPACITY,
                replenishRate: this.config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
                statefulEnabled: this.config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
            })
        }

        let overflowLaneTTLRefreshService: OverflowRedirectService | undefined
        if (this.config.INGESTION_LANE === 'overflow' && this.config.INGESTION_STATEFUL_OVERFLOW_ENABLED) {
            overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
            })
        }

        const eventIngestionRestrictionManager = new EventIngestionRestrictionManager(this.redisPool, {
            pipeline: 'analytics',
            staticDropEventTokens: this.config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
            staticSkipPersonTokens: this.config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
            staticForceOverflowTokens:
                this.config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
        })

        const personsStore: PersonsStore = new BatchWritingPersonsStore(personRepository, ingestionOutputs, {
            dbWriteMode: this.config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            useBatchUpdates: this.config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
            maxConcurrentUpdates: this.config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: this.config.PERSON_PROPERTIES_UPDATE_ALL,
        })

        const groupStore = new BatchWritingGroupStore(ingestionOutputs, groupRepository, clickhouseGroupRepository, {
            maxConcurrentUpdates: this.config.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.config.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.config.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.topHog = new TopHog({
            outputs: ingestionOutputs,
            pipeline: this.config.INGESTION_PIPELINE ?? 'unknown',
            lane: this.config.INGESTION_LANE ?? 'unknown',
        })
        this.topHog.start()

        // 7. Create the ingestion pipeline
        const groupId = this.config.INGESTION_CONSUMER_GROUP_ID

        const joinedPipelineConfig: JoinedIngestionPipelineConfig = {
            eventSchemaEnforcementEnabled: this.config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
            overflowEnabled: this.overflowEnabled(),
            preservePartitionLocality: this.config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
            personsPrefetchEnabled: this.config.PERSONS_PREFETCH_ENABLED,
            cdpHogWatcherSampleRate: this.config.CDP_HOG_WATCHER_SAMPLE_RATE,
            groupId,
            outputs: ingestionOutputs,
            splitAiEventsConfig: parseSplitAiEventsConfig(
                this.config.INGESTION_AI_EVENT_SPLITTING_ENABLED,
                this.config.INGESTION_AI_EVENT_SPLITTING_TEAMS,
                this.config.INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY_TEAMS,
                this.config.INGESTION_AI_EVENT_SPLITTING_PERCENTAGE
            ),
            perDistinctIdOptions: {
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: this.config.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_SYNC_BATCH_SIZE: this.config.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: this.config.PERSON_PROPERTIES_UPDATE_ALL,
            },
        }
        const joinedPipelineDeps: JoinedIngestionPipelineDeps = {
            personsStore,
            groupStore,
            hogTransformer: this.hogTransformer,
            eventFilterManager: new EventFilterManager(this.postgres),
            eventIngestionRestrictionManager,
            eventSchemaEnforcementManager: new EventSchemaEnforcementManager(this.postgres),
            promiseScheduler: this.promiseScheduler,
            overflowRedirectService,
            overflowLaneTTLRefreshService,
            teamManager,
            cookielessManager: this.cookielessManager,
            groupTypeManager,
            topHog: this.topHog,
        }
        this.joinedPipeline = createJoinedIngestionPipeline(joinedPipelineConfig, joinedPipelineDeps)

        // 8. Register the ingest endpoint and service
        this.lifecycle.expressApp.post('/ingest', async (req, res) => {
            await this.handleIngestRequest(req, res)
        })

        const service: PluginServerService = {
            id: 'ingestion-api',
            onShutdown: async () => {
                await this.topHog.stop()
                await this.hogTransformer.stop()
            },
            healthcheck: () => this.isHealthy(),
        }
        this.lifecycle.services.push(service)
    }

    private async handleIngestRequest(
        req: { body: IngestBatchRequest },
        res: { status: (code: number) => { json: (body: IngestBatchResponse) => void } }
    ): Promise<void> {
        const { batch_id, messages: serializedMessages } = req.body

        if (!serializedMessages || serializedMessages.length === 0) {
            res.status(400).json({ batch_id: batch_id ?? '', status: 'error', accepted: 0, error: 'Empty batch' })
            return
        }

        const startTime = Date.now()

        try {
            const messages: Message[] = serializedMessages.map(deserializeKafkaMessage)

            const batch = messages.map((message) => createOkContext({ message }, { message }))
            const feedResult = await this.joinedPipeline.feed(batch)
            if (!feedResult.ok) {
                throw new Error(`Pipeline rejected batch: ${feedResult.reason}`)
            }

            let result = await this.joinedPipeline.next()
            while (result !== null) {
                for (const sideEffect of result.sideEffects ?? []) {
                    void this.promiseScheduler.schedule(sideEffect)
                }
                result = await this.joinedPipeline.next()
            }

            // Wait for all side effects — the HTTP response is the ACK to the
            // Rust consumer, so all work must finish before responding.
            // Note: the joined pipeline has a hardcoded concurrency of 1, so
            // feed() will reject if a batch is already being processed. This
            // is fine for now since we process each request sequentially.
            await Promise.all([this.promiseScheduler.waitForAll(), this.hogTransformer.processInvocationResults()])

            batchesProcessed.inc()
            messagesProcessed.inc(messages.length)
            batchProcessingDuration.observe(Date.now() - startTime)

            res.status(200).json({ batch_id, status: 'ok', accepted: messages.length })
        } catch (err) {
            batchErrors.inc()
            const message = err instanceof Error ? err.message : String(err)
            logger.error('💥', 'Ingestion API batch processing failed', { batch_id, error: message })
            res.status(500).json({ batch_id, status: 'error', accepted: 0, error: message })
        }
    }

    private isHealthy() {
        // TODO: add output producer health checks
        return new HealthCheckResultOk()
    }

    private overflowEnabled(): boolean {
        return (
            !!this.config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
            this.config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.config.INGESTION_CONSUMER_CONSUME_TOPIC
        )
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.cookielessRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                await this.ingestionProducerRegistry?.disconnectAll()
                this.cookielessManager?.shutdown()
            },
        }
    }
}
