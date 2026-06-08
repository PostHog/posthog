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
import { createOutputsRegistry } from '../ingestion/analytics/outputs/registry'
import { createClientWarningsConsumer } from '../ingestion/clientwarnings'
import {
    KafkaIngestionProducerEnvConfig,
    KafkaProducerEnvConfig,
    KafkaWarpstreamProducerEnvConfig,
    getDefaultKafkaIngestionProducerEnvConfig,
    getDefaultKafkaProducerEnvConfig,
    getDefaultKafkaWarpstreamProducerEnvConfig,
} from '../ingestion/common/config'
import { ingestionConsumerService } from '../ingestion/common/ingestion-consumer'
import { KafkaProducerRegistryComponent } from '../ingestion/common/outputs/registry'
import { extend, newScope } from '../ingestion/common/scopes'
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
import { IngestionConsumer, IngestionConsumerDeps } from '../ingestion/ingestion-consumer'
import { IngestionTestingConsumer } from '../ingestion/ingestion-testing-consumer'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../ingestion/personhog'
import { KafkaProducerWrapper } from '../kafka/producer'
import { PluginServerService, RedisPool } from '../types'
import { ServerCommands } from '../utils/commands'
import { PostgresRouter, PostgresRouterComponent } from '../utils/db/postgres'
import { RedisPoolComponent, createRedisPoolFromConfig } from '../utils/db/redis'
import { GeoIPService } from '../utils/geoip'
import { logger } from '../utils/logger'
import { PubSub } from '../utils/pubsub'
import { TeamManagerComponent } from '../utils/team-manager'
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
    private redisPool?: RedisPool
    private cookielessRedisPool?: RedisPool
    private cookielessManager?: CookielessManager
    private pubsub?: PubSub
    private stopSharedServices?: () => Promise<void>

    constructor(config: Partial<IngestionGeneralServerConfig> = {}) {
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

        // 1. Shared infrastructure — postgres + redis lifetimes are owned
        //    by a server-level Scope so consumers can extend off it via
        //    `Scope.extend` to get them as handles without taking
        //    ownership.
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        const sharedInfraScope = newScope('shared-infra', (builder) =>
            builder
                .add('postgres', new PostgresRouterComponent(this.config, this.config.PLUGIN_SERVER_MODE!))
                .add(
                    'redisPool',
                    new RedisPoolComponent({
                        connection: createIngestionRedisConnectionConfig(this.config),
                        poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                        poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                    })
                )
                .add('producerRegistry', new KafkaProducerRegistryComponent(this.config.KAFKA_CLIENT_RACK, this.config))
        )

        // `teamManager` is built inside the extension via its component so
        // it picks up `postgres` from the started infra scope's container
        // and is owned by that scope. The server extracts it from the
        // started container to pass on to CDP services etc.
        const staticDropEventTokens = this.config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        const sharedServicesScope = extend(sharedInfraScope, 'shared', (container, builder) =>
            builder
                .add(
                    'teamManager',
                    // Retry transient team-load failures (e.g. a Postgres pooler scale-down returning
                    // ECONNREFUSED). The team loader runs detached in the LazyLoader buffer, so an un-retried
                    // transient failure can surface as an unhandled rejection and restart the worker.
                    new TeamManagerComponent(container.postgres, {
                        loaderRetry: { retryIntervalMs: 250, retryJitterMs: 250, maxElapsedMs: 5000 },
                    })
                )
                .add('staticDropEventTokens', {
                    start: () => Promise.resolve({ value: staticDropEventTokens, stop: () => Promise.resolve() }),
                })
        )

        const sharedServices = await sharedServicesScope.start()
        this.postgres = sharedServices.container.postgres
        this.redisPool = sharedServices.container.redisPool
        const teamManager = sharedServices.container.teamManager
        this.stopSharedServices = sharedServices.stop
        logger.info('👍', 'Postgres Router ready')
        logger.info('👍', 'Ingestion Redis ready')

        this.pubsub = new PubSub(this.redisPool)
        await this.pubsub.start()

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
            // Producer registry is owned by `sharedInfraScope`; the
            // server reads it back from the started services. Outputs is
            // a typed view over it — built once here for analytics, and
            // separately by each consumer factory as needed.
            const ingestionProducerRegistry = sharedServices.container.producerRegistry
            const ingestionOutputs = createOutputsRegistry().build(ingestionProducerRegistry, this.config)
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

            const ingestionDeps: IngestionConsumerDeps = {
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

            const startClientWarnings = (override?: { topic: string; groupId: string }) => {
                serviceLoaders.push(async () => {
                    const consumerConfig = override
                        ? {
                              ...this.config,
                              INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                              INGESTION_CONSUMER_GROUP_ID: override.groupId,
                          }
                        : this.config
                    const consumerScope = createClientWarningsConsumer(consumerConfig, sharedServicesScope)
                    const { consumer, stop } = await consumerScope.start()
                    return ingestionConsumerService(consumer, stop)
                })
            }

            if (isCombinedMode) {
                // Local dev / hobby: run multiple consumers for all ingestion topics in one process
                const consumersOptions = [
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION, group_id: 'clickhouse-ingestion' },
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL, group_id: 'clickhouse-ingestion-historical' },
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, group_id: 'clickhouse-ingestion-overflow' },
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

                startClientWarnings({
                    topic: 'ingestion-clientwarnings-main-1',
                    groupId: 'ingestion-clientwarnings-main',
                })
            } else if (this.config.INGESTION_PIPELINE === 'clientwarnings') {
                startClientWarnings()
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
            kafkaProducers: [],
            // `redisPool` and `postgres` are owned by `sharedInfraScope` and
            // get torn down by `stopSharedServices()` below. Only
            // cookielessRedisPool stays here — it's not on the scope.
            redisPools: [this.cookielessRedisPool].filter(Boolean) as RedisPool[],
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                this.cookielessManager?.shutdown()
                if (this.stopSharedServices) {
                    await this.stopSharedServices()
                }
            },
        }
    }
}
