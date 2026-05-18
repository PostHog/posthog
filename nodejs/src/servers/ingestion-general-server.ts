import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'

import { initializePrometheusLabels } from '../api/router'
import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig, PluginServerMode } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { createCookielessRedisConnectionConfig, createIngestionRedisConnectionConfig } from '../config/redis-pools'
import { AiOutputsConfig, getDefaultAiOutputsConfig, registerAiOutputs } from '../ingestion/ai/config/outputs'
import { AiServerConfig, AiServerDeps, assembleAiConsumer } from '../ingestion/ai/consumer'
import { AnalyticsServerConfig, AnalyticsServerDeps, assembleAnalyticsConsumer } from '../ingestion/analytics/consumer'
import { createOutputsRegistry } from '../ingestion/analytics/outputs/registry'
import {
    ClientWarningsOutputsConfig,
    getDefaultClientWarningsOutputsConfig,
    registerClientWarningsOutputs,
} from '../ingestion/clientwarnings/config/outputs'
import { createClientWarningsConsumer } from '../ingestion/clientwarnings/consumer'
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
    IngestionConsumerConfig,
    IngestionOutputsConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    PersonHogConfig,
    RedisConnectionsConfig,
    getDefaultIngestionOutputsConfig,
} from '../ingestion/config'
import { CookielessManager } from '../ingestion/cookieless/cookieless-manager'
import {
    HeatmapsOutputsConfig,
    getDefaultHeatmapsOutputsConfig,
    registerHeatmapsOutputs,
} from '../ingestion/heatmaps/config/outputs'
import { HeatmapsServerConfig, HeatmapsServerDeps, assembleHeatmapsConsumer } from '../ingestion/heatmaps/consumer'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../ingestion/personhog'
import { PluginServerService, RedisPool } from '../types'
import { ServerCommands } from '../utils/commands'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { GeoIPService } from '../utils/geoip'
import { logger } from '../utils/logger'
import { PubSub } from '../utils/pubsub'
import { TeamManager } from '../utils/team-manager'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from '../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from '../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from '../worker/ingestion/persons/repositories/postgres-person-repository'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Complete config type for an ingestion-v2 deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - IngestionConsumerConfig: ingestion pipeline, person/group processing, overflow, cookieless, etc.
 * - HogTransformerServiceConfig: CDP keys needed by the hog transformer running in-process
 * - Infrastructure configs: Kafka broker, Postgres, Redis, consumer tuning
 * - Remaining CommonConfig picks: server mode, services, observability
 *
 * This type is the source of truth for which env vars ingestion-events-* deployments need.
 */
export type IngestionGeneralServerConfig = BaseServerConfig &
    IngestionConsumerConfig &
    HogTransformerServiceConfig &
    KafkaBrokerConfig &
    KafkaProducerEnvConfig &
    KafkaWarpstreamProducerEnvConfig &
    KafkaIngestionProducerEnvConfig &
    IngestionOutputsConfig &
    AiOutputsConfig &
    HeatmapsOutputsConfig &
    ClientWarningsOutputsConfig &
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

export class IngestionGeneralServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionGeneralServerConfig

    private postgres?: PostgresRouter
    private ingestionProducerRegistry?: KafkaProducerRegistry<ProducerName>
    private redisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub

    constructor(config: Partial<IngestionGeneralServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultKafkaProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaIngestionProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultIngestionOutputsConfig()),
            ...overrideConfigWithEnv(getDefaultAiOutputsConfig()),
            ...overrideConfigWithEnv(getDefaultHeatmapsOutputsConfig()),
            ...overrideConfigWithEnv(getDefaultClientWarningsOutputsConfig()),
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
        const isCombinedMode = this.config.PLUGIN_SERVER_MODE === PluginServerMode.ingestion_v2_combined

        // Validate INGESTION_PIPELINE before any IO so misconfigured pods fail
        // fast instead of getting stuck trying to connect to brokers first.
        if (!isCombinedMode) {
            const validPipelines = ['analytics', 'ai', 'heatmaps', 'clientwarnings']
            if (!this.config.INGESTION_PIPELINE || !validPipelines.includes(this.config.INGESTION_PIPELINE)) {
                throw new Error(
                    `INGESTION_PIPELINE must be set to one of: ${validPipelines.join(', ')} (got: ${
                        this.config.INGESTION_PIPELINE ?? '<unset>'
                    })`
                )
            }
        }

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

        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        // Build producer registry — producer creation blocks until the broker
        // is reachable (rdkafka retries indefinitely), so the server will hang
        // here if a broker is down and the pod never becomes healthy.
        this.ingestionProducerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const ingestionOutputs = createOutputsRegistry().build(this.ingestionProducerRegistry, this.config)
        const clickhouseGroupRepository = new ClickhouseGroupRepository(ingestionOutputs)

        const hogTransformerDeps: HogTransformerServiceDeps = {
            geoipService,
            postgres: this.postgres,
            pubSub: this.pubsub,
            encryptedFields,
            integrationManager,
            monitoringOutputs: ingestionOutputs,
            teamManager,
        }

        const ingestionDeps: AnalyticsServerDeps = {
            postgres: this.postgres,
            redisPool: this.redisPool,
            outputs: ingestionOutputs,
            teamManager,
            groupTypeManager,
            groupRepository,
            clickhouseGroupRepository,
            personRepository,
            cookielessManager: this.cookielessManager,
            hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
        }

        // Per-pipeline consumer launchers. Each builds the right config and deps
        // and pushes a loader onto `serviceLoaders`. Topic overrides are used in
        // combined mode where one process runs all pipelines; in single-pipeline
        // mode the caller leaves the override unset and the deployer-supplied
        // INGESTION_CONSUMER_CONSUME_TOPIC / _GROUP_ID drive the consumer.
        const startAnalytics = (override?: { topic: string; groupId: string }) => {
            serviceLoaders.push(async () => {
                const consumerConfig: AnalyticsServerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumer = assembleAnalyticsConsumer(consumerConfig, ingestionDeps)
                await consumer.start()
                return consumer.service
            })
        }

        const startAi = (override?: { topic: string; groupId: string }) => {
            const aiOutputs = registerAiOutputs().build(this.ingestionProducerRegistry!, this.config)
            const aiServerDeps: AiServerDeps = {
                postgres: this.postgres!,
                redisPool: this.redisPool!,
                outputs: aiOutputs,
                teamManager,
                groupTypeManager,
                groupRepository,
                clickhouseGroupRepository: new ClickhouseGroupRepository(aiOutputs),
                personRepository,
                cookielessManager: this.cookielessManager!,
                hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
            }
            serviceLoaders.push(async () => {
                const consumerConfig: AiServerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumer = assembleAiConsumer(consumerConfig, aiServerDeps)
                await consumer.start()
                return consumer.service
            })
        }

        const startHeatmaps = (override?: { topic: string; groupId: string }) => {
            const heatmapsOutputs = registerHeatmapsOutputs().build(this.ingestionProducerRegistry!, this.config)
            const heatmapsServerDeps: HeatmapsServerDeps = {
                postgres: this.postgres!,
                redisPool: this.redisPool!,
                outputs: heatmapsOutputs,
                teamManager,
                groupTypeManager,
                groupRepository,
                clickhouseGroupRepository: new ClickhouseGroupRepository(heatmapsOutputs),
                personRepository,
                cookielessManager: this.cookielessManager!,
                hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
            }
            serviceLoaders.push(async () => {
                const consumerConfig: HeatmapsServerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumer = assembleHeatmapsConsumer(consumerConfig, heatmapsServerDeps)
                await consumer.start()
                return consumer.service
            })
        }

        const startClientWarnings = (override?: { topic: string; groupId: string }) => {
            const clientWarningsOutputs = registerClientWarningsOutputs().build(
                this.ingestionProducerRegistry!,
                this.config
            )
            serviceLoaders.push(async () => {
                const consumerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumer = createClientWarningsConsumer(consumerConfig, {
                    outputs: clientWarningsOutputs,
                    teamManager,
                })
                await consumer.start()
                return consumer.service
            })
        }

        if (isCombinedMode) {
            // Local dev / hobby: run every pipeline in one process. Each consumer
            // gets its own per-pipeline outputs registry — the registries don't
            // share env-var prefixes, so the same consumer can be deployed
            // standalone with only its own keys set.
            startAnalytics({ topic: KAFKA_EVENTS_PLUGIN_INGESTION, groupId: 'clickhouse-ingestion' })
            startAnalytics({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
                groupId: 'clickhouse-ingestion-historical',
            })
            startAnalytics({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                groupId: 'clickhouse-ingestion-overflow',
            })
            startAi({ topic: this.config.AI_INGESTION_CONSUME_TOPIC, groupId: this.config.AI_INGESTION_GROUP_ID })
            startHeatmaps({ topic: 'heatmaps_ingestion', groupId: 'heatmaps_ingestion' })
            startClientWarnings({ topic: 'client_iwarnings_ingestion', groupId: 'client_iwarnings_ingestion' })
        } else {
            // Production ingestion-v2: a single pipeline per pod, selected by
            // INGESTION_PIPELINE. The deployer-supplied INGESTION_CONSUMER_*
            // env vars drive the topic and group id.
            switch (this.config.INGESTION_PIPELINE) {
                case 'analytics':
                    startAnalytics()
                    break
                case 'ai':
                    startAi()
                    break
                case 'heatmaps':
                    startHeatmaps()
                    break
                case 'clientwarnings':
                    startClientWarnings()
                    break
                default:
                    throw new Error(
                        `INGESTION_PIPELINE must be set to one of: analytics, ai, heatmaps, clientwarnings (got: ${
                            this.config.INGESTION_PIPELINE ?? '<unset>'
                        })`
                    )
            }
        }

        // ServerCommands is always created
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
                await this.ingestionProducerRegistry?.disconnectAll()
                await this.cookielessManager?.stop()
            },
        }
    }
}
