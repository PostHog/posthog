import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '~/common/config/redis-pools'
import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig, createPersonHogClient } from '~/common/personhog'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { ServerCommands } from '~/common/utils/commands'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { ErrorTrackingSettingsManager } from '~/common/utils/error-tracking-settings-manager'
import { GeoIPService } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager, CookielessServerConfig } from '~/ingestion/common/cookieless/cookieless-manager'
import { createIngestionProducerRegistry } from '~/ingestion/common/outputs/producer-registry'
import {
    KafkaDownstreamProducerEnvConfig,
    KafkaUpstreamProducerEnvConfig,
    ProducerName,
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import {
    ErrorTrackingConsumerConfig,
    ErrorTrackingOutputsConfig,
    getDefaultErrorTrackingConsumerConfig,
    getDefaultErrorTrackingOutputsConfig,
} from '~/ingestion/pipelines/errortracking/config'
import { ErrorTrackingConsumer } from '~/ingestion/pipelines/errortracking/error-tracking-consumer'
import { createOutputsRegistry } from '~/ingestion/pipelines/errortracking/outputs/registry'

import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig } from '../common/config'
import {
    DatabaseConnectionConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    RedisConnectionsConfig,
    getDefaultIngestionConsumerConfig,
} from '../ingestion/config'
import { PluginServerService, RedisPool } from '../types'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Complete config type for an error tracking ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - ErrorTrackingConsumerConfig: error tracking pipeline, cymbal, overflow
 * - HogTransformerServiceConfig: CDP keys needed by the hog transformer running in-process
 * - Infrastructure configs: Kafka broker, Postgres, Redis, consumer tuning
 * - Remaining CommonConfig picks: server mode, services, observability
 */
export type ErrorTrackingServerConfig = BaseServerConfig &
    ErrorTrackingConsumerConfig &
    HogTransformerServiceConfig &
    KafkaBrokerConfig &
    KafkaUpstreamProducerEnvConfig &
    KafkaDownstreamProducerEnvConfig &
    ErrorTrackingOutputsConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    KafkaConsumerBaseConfig &
    PersonHogConfig &
    CookielessServerConfig &
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'MMDB_FILE_LOCATION'
        | 'CAPTURE_INTERNAL_URL'
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class ErrorTrackingServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: ErrorTrackingServerConfig

    private postgres?: PostgresRouter
    private producerRegistry?: KafkaProducerRegistry<ProducerName>
    private redisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub

    constructor(config: Partial<ErrorTrackingServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
            ...overrideConfigWithEnv(getDefaultErrorTrackingConsumerConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaUpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultErrorTrackingOutputsConfig()),
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
        initializePrometheusLabels(
            this.config.INGESTION_PIPELINE ?? 'errortracking',
            this.config.INGESTION_LANE ?? 'main'
        )

        // 1. Shared infrastructure
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.producerRegistry = await createIngestionProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
        logger.info('👍', 'Kafka ready')

        logger.info('🤔', 'Connecting to ingestion Redis...')
        this.redisPool = createRedisPoolFromConfig({
            connection: createIngestionRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'Ingestion Redis ready')

        logger.info('🤔', 'Connecting to cookieless Redis...')
        this.cookielessRedisPool = createRedisPoolFromConfig({
            connection: createCookielessRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'Cookieless Redis ready')

        this.cookielessManager = new CookielessManager(this.config, this.cookielessRedisPool)

        this.pubsub = new PubSub(this.redisPool)
        await this.pubsub.start()

        const teamManager = new TeamManager(this.postgres)
        const errorTrackingSettingsManager = this.config.ERROR_TRACKING_RATE_LIMITER_ENABLED
            ? new ErrorTrackingSettingsManager(this.postgres)
            : undefined

        // 2. Services needed by ErrorTrackingConsumer and HogTransformer
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personhogClient = createPersonHogClient(this.config)
        const clientLabel = this.config.PLUGIN_SERVER_MODE ?? 'unknown'

        if (!personhogClient) {
            throw new Error(
                'PersonHog client is required for error tracking — set PERSONHOG_ENABLED=true and PERSONHOG_ADDR'
            )
        }

        const personRepository = new PersonHogPersonReadRepository(personhogClient, clientLabel)
        const groupRepository = new PersonHogGroupReadRepository(personhogClient, clientLabel)
        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub, this.postgres, encryptedFields)

        const hogTransformerDeps: HogTransformerServiceDeps = {
            geoipService,
            postgres: this.postgres,
            pubSub: this.pubsub,
            encryptedFields,
            integrationManager,
            monitoringOutputs: outputs,
            teamManager,
        }

        // 3. Error tracking consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumer = new ErrorTrackingConsumer(
                {
                    groupId: this.config.ERROR_TRACKING_CONSUMER_GROUP_ID,
                    topic: this.config.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
                    cymbalBaseUrl: this.config.ERROR_TRACKING_CYMBAL_BASE_URL,
                    cymbalTimeoutMs: this.config.ERROR_TRACKING_CYMBAL_TIMEOUT_MS,
                    cymbalMaxBodyBytes: this.config.ERROR_TRACKING_CYMBAL_MAX_BODY_BYTES,
                    lane: this.config.INGESTION_LANE ?? 'main',
                    overflowMode: this.config.INGESTION_OVERFLOW_MODE,
                    overflowBucketCapacity: this.config.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
                    overflowBucketReplenishRate: this.config.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
                    statefulOverflowRedisTTLSeconds: this.config.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
                    statefulOverflowLocalCacheTTLSeconds:
                        this.config.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                    preservePartitionLocality: this.config.ERROR_TRACKING_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    pipeline: this.config.INGESTION_PIPELINE ?? 'errortracking',
                    rateLimiterEnabled: this.config.ERROR_TRACKING_RATE_LIMITER_ENABLED,
                    rateLimiterReportingMode: this.config.ERROR_TRACKING_RATE_LIMITER_REPORTING_MODE,
                    rateLimiterRedisHost: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_HOST,
                    rateLimiterRedisPort: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_PORT,
                    rateLimiterRedisTls: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_TLS,
                    rateLimiterTtlSeconds: this.config.ERROR_TRACKING_RATE_LIMITER_TTL_SECONDS,
                    perIssueGuardThreshold: this.config.ERROR_TRACKING_PER_ISSUE_GUARD_THRESHOLD,
                    perIssueGuardWindowTtlSeconds: this.config.ERROR_TRACKING_PER_ISSUE_GUARD_WINDOW_TTL_SECONDS,
                    perIssueGuardCooldownTtlSeconds: this.config.ERROR_TRACKING_PER_ISSUE_GUARD_COOLDOWN_TTL_SECONDS,
                    fallbackRedisUrl: this.config.REDIS_URL,
                    rateLimiterRedisPoolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                    rateLimiterRedisPoolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                },
                {
                    outputs,
                    teamManager,
                    errorTrackingSettingsManager,
                    hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
                    groupTypeManager: new ReadOnlyGroupTypeManager(groupRepository),
                    cookielessManager: this.cookielessManager!,
                    redisPool: this.redisPool!,
                    personRepository,
                }
            )
            await consumer.start()
            return consumer.service
        })

        serviceLoaders.push(() => {
            const serverCommands = new ServerCommands(this.pubsub!)
            this.lifecycle.expressApp.use('/', serverCommands.router())
            return Promise.resolve(serverCommands.service)
        })

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.cookielessRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
                this.cookielessManager?.shutdown()
            },
        }
    }
}
