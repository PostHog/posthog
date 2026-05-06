import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'

import { initializePrometheusLabels } from '../api/router'
import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import { createIngestionRedisConnectionConfig } from '../config/redis-pools'
import {
    KafkaIngestionProducerEnvConfig,
    KafkaProducerEnvConfig,
    KafkaWarpstreamProducerEnvConfig,
    getDefaultKafkaIngestionProducerEnvConfig,
    getDefaultKafkaProducerEnvConfig,
    getDefaultKafkaWarpstreamProducerEnvConfig,
} from '../ingestion/common/config'
import { ProducerName } from '../ingestion/common/outputs'
import { createProducerRegistry } from '../ingestion/common/outputs/registry'
import {
    DatabaseConnectionConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    PersonHogConfig,
    RedisConnectionsConfig,
} from '../ingestion/config'
import {
    ErrorTrackingConsumerConfig,
    ErrorTrackingOutputsConfig,
    getDefaultErrorTrackingOutputsConfig,
} from '../ingestion/error-tracking/config'
import { ErrorTrackingConsumer } from '../ingestion/error-tracking/error-tracking-consumer'
import { createOutputsRegistry } from '../ingestion/error-tracking/outputs/registry'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../ingestion/personhog'
import { PluginServerService, RedisPool } from '../types'
import { ServerCommands } from '../utils/commands'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { ErrorTrackingSettingsManager } from '../utils/error-tracking-settings-manager'
import { GeoIPService } from '../utils/geoip'
import { logger } from '../utils/logger'
import { PubSub } from '../utils/pubsub'
import { TeamManager } from '../utils/team-manager'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { PostgresGroupRepository } from '../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from '../worker/ingestion/persons/repositories/postgres-person-repository'
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
    KafkaProducerEnvConfig &
    KafkaWarpstreamProducerEnvConfig &
    KafkaIngestionProducerEnvConfig &
    ErrorTrackingOutputsConfig &
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
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class ErrorTrackingServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: ErrorTrackingServerConfig

    private postgres?: PostgresRouter
    private producerRegistry?: KafkaProducerRegistry<ProducerName>
    private redisPool?: RedisPool
    private pubsub?: PubSub

    constructor(config: Partial<ErrorTrackingServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultKafkaProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaIngestionProducerEnvConfig()),
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
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
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
        const errorTrackingSettingsManager = this.config.ERROR_TRACKING_RATE_LIMITER_ENABLED
            ? new ErrorTrackingSettingsManager(this.postgres)
            : undefined

        // 2. Services needed by ErrorTrackingConsumer and HogTransformer
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personhogClient = createPersonHogClient(this.config)
        const clientLabel = this.config.PLUGIN_SERVER_MODE ?? 'unknown'

        const postgresPersonRepository = new PostgresPersonRepository(this.postgres)
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
                    overflowEnabled:
                        !!this.config.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC &&
                        this.config.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC !==
                            this.config.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
                    overflowBucketCapacity: this.config.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
                    overflowBucketReplenishRate: this.config.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
                    statefulOverflowEnabled: this.config.ERROR_TRACKING_STATEFUL_OVERFLOW_ENABLED,
                    statefulOverflowRedisTTLSeconds: this.config.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
                    statefulOverflowLocalCacheTTLSeconds:
                        this.config.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                    pipeline: this.config.INGESTION_PIPELINE ?? 'error_tracking',
                    rateLimiterEnabled: this.config.ERROR_TRACKING_RATE_LIMITER_ENABLED,
                    rateLimiterReportingMode: this.config.ERROR_TRACKING_RATE_LIMITER_REPORTING_MODE,
                    rateLimiterRedisHost: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_HOST,
                    rateLimiterRedisPort: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_PORT,
                    rateLimiterRedisTls: this.config.ERROR_TRACKING_RATE_LIMITER_REDIS_TLS,
                    rateLimiterTtlSeconds: this.config.ERROR_TRACKING_RATE_LIMITER_TTL_SECONDS,
                    fallbackRedisUrl: this.config.REDIS_URL,
                    rateLimiterRedisPoolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                    rateLimiterRedisPoolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                },
                {
                    outputs,
                    teamManager,
                    errorTrackingSettingsManager,
                    hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
                    groupTypeManager: new GroupTypeManager(groupRepository, teamManager),
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
            redisPools: [this.redisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
