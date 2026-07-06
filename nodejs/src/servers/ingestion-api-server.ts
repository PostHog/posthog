import { Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import {
    createCookielessRedisConnectionConfig,
    createFeatureFlagCalledDedupRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '~/common/config/redis-pools'
import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from '~/common/groups/repositories/postgres-group-repository'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig, buildGroupRepository, buildPersonRepository, createPersonHogClient } from '~/common/personhog'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { EventIngestionRestrictionManagerComponent } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { GeoIPService } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { createIngestionProducerRegistry } from '~/ingestion/common/outputs/producer-registry'
import {
    KafkaDownstreamProducerEnvConfig,
    KafkaUpstreamProducerEnvConfig,
    ProducerName,
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { BatchWritingPersonsStore } from '~/ingestion/common/persons/batch-writing-person-store'
import { PersonsStore } from '~/ingestion/common/persons/persons-store'
import { createOkContext } from '~/ingestion/framework/helpers'
import { TopHog } from '~/ingestion/framework/tophog'
import { createAiEventSubpipeline } from '~/ingestion/pipelines/ai'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineDeps,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from '~/ingestion/pipelines/analytics/joined-ingestion-pipeline'
import { createOutputsRegistry } from '~/ingestion/pipelines/analytics/outputs/registry'

import {
    HogTransformerService,
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig } from '../common/config'
import { deserializeKafkaMessage } from '../ingestion/api/kafka-message-converter'
import { IngestBatchRequest, IngestBatchResponse } from '../ingestion/api/types'
import { EventFilterManagerComponent } from '../ingestion/common/event-filters'
import { createFeatureFlagCalledDedupService } from '../ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { MainLaneOverflowRedirect } from '../ingestion/common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '../ingestion/common/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '../ingestion/common/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '../ingestion/common/overflow-redirect/overflow-redis-repository'
import {
    DatabaseConnectionConfig,
    IngestionConsumerConfig,
    IngestionOutputsConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    RedisConnectionsConfig,
    getDefaultIngestionConsumerConfig,
    getDefaultIngestionOutputsConfig,
} from '../ingestion/config'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    RedisPool,
} from '../types'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

export type IngestionApiServerConfig = BaseServerConfig &
    IngestionConsumerConfig &
    IngestionOutputsConfig &
    HogTransformerServiceConfig &
    KafkaUpstreamProducerEnvConfig &
    KafkaDownstreamProducerEnvConfig &
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

const batchCapacityRejections = new Counter({
    name: 'ingestion_api_batch_capacity_rejections_total',
    help: 'Total number of batches rejected because the pipeline was at concurrent batch capacity',
})

const batchesInFlight = new Gauge({
    name: 'ingestion_api_batches_in_flight',
    help: 'Number of accepted batches currently being processed by the ingestion API (concurrent batches)',
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
    private featureFlagCalledDedupRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub
    private personsStore?: BatchWritingPersonsStore
    private groupStore?: BatchWritingGroupStore

    private joinedPipeline!: ReturnType<
        typeof createJoinedIngestionPipeline<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>
    >
    private promiseScheduler = new PromiseScheduler()
    private hogTransformer!: HogTransformerService
    private topHog!: TopHog

    // Latched on the first unexpected pipeline error. The joinedPipeline is a
    // single long-lived instance shared across all requests; a throw can leave
    // it permanently poisoned (e.g. a group exhausted retries), so we mirror the
    // Kafka consumer's contract of crashing and rebuilding rather than serving a
    // wedged pipeline forever.
    private fatalError?: Error

    constructor(config: Partial<IngestionApiServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaUpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
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

        // Dedicated $feature_flag_called dedup Redis; falls back to ingestion until the host is set.
        this.featureFlagCalledDedupRedisPool = createRedisPoolFromConfig({
            connection: createFeatureFlagCalledDedupRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })

        const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)

        // 4. Kafka producers for pipeline outputs (not consuming from Kafka)
        this.ingestionProducerRegistry = await createIngestionProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(
            this.config
        )
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
                overflowType: 'events',
            })
        }

        let overflowLaneTTLRefreshService: OverflowRedirectService | undefined
        if (this.config.INGESTION_OVERFLOW_MODE === 'consume') {
            overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                overflowType: 'events',
            })
        }

        const { value: eventIngestionRestrictionManager, stop: stopEventIngestionRestrictionManager } =
            await new EventIngestionRestrictionManagerComponent(this.redisPool, {
                pipeline: 'analytics',
                staticDropEventTokens: this.config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
                staticSkipPersonTokens:
                    this.config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
                staticForceOverflowTokens:
                    this.config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter(Boolean),
            }).start()

        this.personsStore = new BatchWritingPersonsStore(personRepository, ingestionOutputs, {
            dbWriteMode: this.config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            useBatchUpdates: this.config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
            maxConcurrentUpdates: this.config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: this.config.PERSON_PROPERTIES_UPDATE_ALL,
        })
        const personsStore: PersonsStore = this.personsStore

        this.groupStore = new BatchWritingGroupStore(ingestionOutputs, groupRepository, clickhouseGroupRepository, {
            maxConcurrentUpdates: this.config.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.config.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.config.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })
        const groupStore = this.groupStore

        this.topHog = new TopHog({
            outputs: ingestionOutputs,
            pipeline: this.config.INGESTION_PIPELINE ?? 'unknown',
            lane: this.config.INGESTION_LANE ?? 'unknown',
        })
        this.topHog.start()

        // 7. Create the ingestion pipeline
        const joinedPipelineConfig: JoinedIngestionPipelineConfig = {
            eventSchemaEnforcementEnabled: this.config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
            overflowEnabled: this.overflowEnabled(),
            preservePartitionLocality: this.config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
            personsPrefetchEnabled: this.config.PERSONS_PREFETCH_ENABLED,
            cdpHogWatcherSampleRate: this.config.CDP_HOG_WATCHER_SAMPLE_RATE,
            outputs: ingestionOutputs,
            perDistinctIdOptions: {
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: this.config.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_SYNC_BATCH_SIZE: this.config.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_MERGE_EVENTS_ENABLED: this.config.PERSON_MERGE_EVENTS_ENABLED,
                PERSON_MERGE_EVENTS_PARTITION_COUNT: this.config.PERSON_MERGE_EVENTS_PARTITION_COUNT,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: this.config.PERSON_PROPERTIES_UPDATE_ALL,
                FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: this.config.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
            },
            concurrentBatches: this.config.INGESTION_WORKER_CONCURRENT_BATCHES,
        }
        const eventFilterManagerStarted = await new EventFilterManagerComponent(this.postgres).start()
        const featureFlagCalledDedupService = createFeatureFlagCalledDedupService(
            this.featureFlagCalledDedupRedisPool,
            this.config
        )

        const joinedPipelineDeps: JoinedIngestionPipelineDeps = {
            personsStore,
            groupStore,
            hogTransformer: this.hogTransformer,
            aiSubpipelineFactory: createAiEventSubpipeline,
            eventFilterManager: eventFilterManagerStarted.value,
            eventIngestionRestrictionManager,
            eventSchemaEnforcementManager: new EventSchemaEnforcementManager(this.postgres),
            promiseScheduler: this.promiseScheduler,
            overflowRedirectService,
            overflowLaneTTLRefreshService,
            featureFlagCalledDedupService,
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
                await eventFilterManagerStarted.stop()
                await stopEventIngestionRestrictionManager()
            },
            healthcheck: () => this.isHealthy(),
        }
        this.lifecycle.services.push(service)
    }

    private async handleIngestRequest(
        req: { body: IngestBatchRequest },
        res: {
            status: (code: number) => { json: (body: IngestBatchResponse) => void }
        }
    ): Promise<void> {
        const { batch_id, messages: serializedMessages } = req.body

        if (!serializedMessages || serializedMessages.length === 0) {
            res.status(400).json({ batch_id: batch_id ?? '', status: 'error', accepted: 0, error: 'Empty batch' })
            return
        }

        const startTime = Date.now()

        // Tracks whether this batch was accepted, so the `finally` only
        // decrements the in-flight gauge for batches that incremented it.
        let inFlight = false

        try {
            const messages: Message[] = serializedMessages.map(deserializeKafkaMessage)

            const batch = messages.map((message) => createOkContext({ message }, { message }))
            const feedResult = await this.joinedPipeline.feed(batch)
            if (!feedResult.ok) {
                // Capacity rejection should not happen under correct consumer
                // behavior — the Rust consumer holds a per-worker Semaphore
                // sized to INGESTION_WORKER_CONCURRENT_BATCHES and is supposed
                // to wait (natural backpressure) before sending a batch that
                // would exceed the worker's capacity. If we land here, the
                // consumer's tracking is wrong or its env-var value disagrees
                // with ours. Respond 503 so the consumer surfaces it as a
                // distinct error (TransportError::WorkerBusy) and the alarm is
                // visible in `ingestion_api_batch_capacity_rejections_total`.
                // Use the typed `kind` discriminator (not the human-readable
                // `reason` string) so a future BatchingPipeline message tweak
                // can't silently downgrade us to a fall-through 500 — which
                // the Rust transport treats as retriable.
                if (feedResult.kind === 'at_capacity') {
                    batchCapacityRejections.inc()
                    res.status(503).json({
                        batch_id: batch_id ?? '',
                        status: 'error',
                        accepted: 0,
                        error: feedResult.reason,
                    })
                    return
                }
                throw new Error(`Pipeline rejected batch: ${feedResult.reason}`)
            }

            // Batch accepted into the pipeline — it now occupies a concurrent
            // slot until processing completes below.
            batchesInFlight.inc()
            inFlight = true

            let result = await this.joinedPipeline.next()
            while (result !== null) {
                for (const sideEffect of result.sideEffects ?? []) {
                    void this.promiseScheduler.schedule(sideEffect)
                }
                result = await this.joinedPipeline.next()
            }

            // Wait for all side effects — the HTTP response is the ACK to the
            // Rust consumer, so all work must finish before responding. The hog
            // transformer drain is scheduled as a side effect by the pipeline's
            // afterBatch flush step, so it's covered by waitForAll().
            await this.promiseScheduler.waitForAll()

            batchesProcessed.inc()
            messagesProcessed.inc(messages.length)
            batchProcessingDuration.observe(Date.now() - startTime)

            res.status(200).json({ batch_id, status: 'ok', accepted: messages.length })
        } catch (err) {
            batchErrors.inc()
            const error = err instanceof Error ? err : new Error(String(err))
            logger.error('💥', 'Ingestion API batch processing failed', { batch_id, error: error.message })
            // A throw here can leave the shared pipeline permanently poisoned, so
            // mirror the Kafka consumer's crash-and-rebuild contract. Respond 500
            // (the Rust transport treats it as retriable and redelivers), mark the
            // server unhealthy, and shut down so the supervisor rebuilds a fresh
            // pipeline instead of serving a wedged one. Trigger the shutdown once:
            // concurrent in-flight requests can all fail on the same poisoned
            // pipeline, but only the first should start teardown.
            if (!this.fatalError) {
                this.fatalError = error
                void this.stop(error)
            }
            res.status(500).json({ batch_id, status: 'error', accepted: 0, error: error.message })
        } finally {
            if (inFlight) {
                batchesInFlight.dec()
            }
        }
    }

    private isHealthy(): HealthCheckResult {
        // TODO: add output producer health checks
        if (this.fatalError) {
            return new HealthCheckResultError('Ingestion pipeline crashed', { error: this.fatalError.message })
        }
        return new HealthCheckResultOk()
    }

    private overflowEnabled(): boolean {
        return this.config.INGESTION_OVERFLOW_MODE === 'redirect'
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.cookielessRedisPool, this.featureFlagCalledDedupRedisPool].filter(
                Boolean
            ) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                // No Kafka offsets in this server — drain buffered writes before
                // shutdown so shutdown() can assert a clean cache.
                if (this.personsStore) {
                    await this.personsStore.flushAndProduceMessages()
                    await this.personsStore.shutdown()
                }
                if (this.groupStore) {
                    await this.groupStore.flush()
                    await this.groupStore.shutdown()
                }
                this.cookielessManager?.shutdown()
                await this.ingestionProducerRegistry?.disconnectAll()
            },
        }
    }
}
