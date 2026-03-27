import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'

import { initializePrometheusLabels } from '../api/router'
import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig, PluginServerMode } from '../common/config'
import { defaultConfig } from '../config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { createCookielessRedisConnectionConfig, createIngestionRedisConnectionConfig } from '../config/redis-pools'
import { INGESTION_OUTPUT_DEFINITIONS } from '../ingestion/analytics/config/outputs'
import { PRODUCER_CONFIG_MAP, ProducerName } from '../ingestion/analytics/config/producers'
import {
    DatabaseConnectionConfig,
    IngestionConsumerConfig,
    KafkaBrokerConfig,
    KafkaConsumerBaseConfig,
    RedisConnectionsConfig,
} from '../ingestion/config'
import { CookielessManager } from '../ingestion/cookieless/cookieless-manager'
import { IngestionConsumer, IngestionConsumerDeps } from '../ingestion/ingestion-consumer'
import { IngestionTestingConsumer } from '../ingestion/ingestion-testing-consumer'
import { KafkaProducerRegistry, resolveIngestionOutputs } from '../ingestion/outputs'
import { KafkaProducerWrapper } from '../kafka/producer'
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
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    KafkaConsumerBaseConfig &
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'MMDB_FILE_LOCATION'
        | 'CAPTURE_INTERNAL_URL'
        | 'LAZY_LOADER_DEFAULT_BUFFER_MS'
        | 'LAZY_LOADER_MAX_SIZE'
        | 'TASKS_PER_WORKER'
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
    private kafkaProducer?: KafkaProducerWrapper
    private kafkaMetricsProducer?: KafkaProducerWrapper
    private ingestionProducerRegistry?: KafkaProducerRegistry<ProducerName>
    private redisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub

    constructor(config: Partial<IngestionGeneralServerConfig> = {}) {
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

        // 1. Shared infrastructure
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE!)
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

        // 2. Ingestion + CDP shared services (geoip, repos, encryption)
        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const personRepository = new PostgresPersonRepository(this.postgres, {
            calculatePropertiesSize: this.config.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
        })
        const groupRepository = new PostgresGroupRepository(this.postgres)
        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub, this.postgres, encryptedFields)
        const internalCaptureService = new InternalCaptureService(this.config)

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

        const isTestingMode = this.config.PLUGIN_SERVER_MODE === PluginServerMode.ingestion_v2_testing
        const isCombinedMode = this.config.PLUGIN_SERVER_MODE === PluginServerMode.ingestion_v2_combined

        if (isTestingMode) {
            serviceLoaders.push(async () => {
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
        } else {
            const hogTransformerDeps: HogTransformerServiceDeps = {
                geoipService,
                postgres: this.postgres,
                pubSub: this.pubsub,
                encryptedFields,
                integrationManager,
                kafkaProducer: this.kafkaMetricsProducer,
                teamManager,
                internalCaptureService,
            }

            // Resolve ingestion outputs — producer creation blocks until the broker
            // is reachable (rdkafka retries indefinitely), so the server will hang
            // here if a broker is down and the pod never becomes healthy.
            this.ingestionProducerRegistry = new KafkaProducerRegistry(
                this.config.KAFKA_CLIENT_RACK,
                PRODUCER_CONFIG_MAP
            )
            const ingestionOutputs = await resolveIngestionOutputs(
                this.ingestionProducerRegistry,
                INGESTION_OUTPUT_DEFINITIONS
            )
            const clickhouseGroupRepository = new ClickhouseGroupRepository(ingestionOutputs)

            const ingestionDeps: IngestionConsumerDeps = {
                postgres: this.postgres,
                redisPool: this.redisPool,
                kafkaProducer: this.kafkaProducer,
                kafkaMetricsProducer: this.kafkaMetricsProducer,
                outputs: ingestionOutputs,
                teamManager,
                groupTypeManager,
                groupRepository,
                clickhouseGroupRepository,
                personRepository,
                cookielessManager: this.cookielessManager,
                hogTransformer: createHogTransformerService(this.config, hogTransformerDeps),
            }

            if (isCombinedMode) {
                // Local dev / hobby: run multiple consumers for all ingestion topics in one process
                const consumersOptions = [
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION, group_id: 'clickhouse-ingestion' },
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL, group_id: 'clickhouse-ingestion-historical' },
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
            } else {
                // Production ingestion-v2: single consumer using config-provided topic
                serviceLoaders.push(async () => {
                    const consumer = new IngestionConsumer(this.config, ingestionDeps)
                    await consumer.start()
                    return consumer.service
                })
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
            kafkaProducers: [this.kafkaProducer, this.kafkaMetricsProducer].filter(Boolean) as KafkaProducerWrapper[],
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
