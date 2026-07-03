import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from '~/common/config/kafka-topics'
import {
    createCookielessRedisConnectionConfig,
    createFeatureFlagCalledDedupRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '~/common/config/redis-pools'
import { HogTransformerComponent } from '~/common/hog-transformations/hog-transformer-component'
import { IngestionOutputsComponent } from '~/common/outputs/ingestion-outputs'
import { PersonHogConfig } from '~/common/personhog'
import { PersonHogRoutedRepositoriesComponent } from '~/common/personhog/personhog-routed-repositories-component'
import { ServerCommands } from '~/common/utils/commands'
import { PostgresRouter, PostgresRouterComponent } from '~/common/utils/db/postgres'
import { RedisPoolComponent } from '~/common/utils/db/redis'
import { GeoIPService } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManagerComponent } from '~/common/utils/team-manager'
import { CookielessManagerComponent } from '~/ingestion/common/cookieless/cookieless-manager'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import {
    KafkaDownstreamProducerEnvConfig,
    KafkaUpstreamProducerEnvConfig,
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { createAiConsumer, createAiEventSubpipeline } from '~/ingestion/pipelines/ai'
import { createOutputsRegistry as createAiOutputsRegistry } from '~/ingestion/pipelines/ai/outputs/registry'
import { createAnalyticsConsumer } from '~/ingestion/pipelines/analytics'
import { createOutputsRegistry } from '~/ingestion/pipelines/analytics/outputs/registry'
import { createClientWarningsConsumer } from '~/ingestion/pipelines/clientwarnings'
import { createHeatmapsConsumer } from '~/ingestion/pipelines/heatmaps'

import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '../cdp/hog-transformations/hog-transformer.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig, PluginServerMode } from '../common/config'
import { ingestionConsumerService } from '../ingestion/common/ingestion-consumer'
import { extend, newScope } from '../ingestion/common/scopes'
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
import { PluginServerService, RedisPool } from '../types'
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
    KafkaUpstreamProducerEnvConfig &
    KafkaDownstreamProducerEnvConfig &
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
    private pubsub?: PubSub
    private stopSharedServices?: () => Promise<void>

    constructor(config: Partial<IngestionGeneralServerConfig> = {}) {
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
                // Cookieless Redis is a separate pool, shared by every consumer that runs cookieless
                // processing (analytics, heatmaps, …).
                .add(
                    'cookielessRedisPool',
                    new RedisPoolComponent({
                        connection: createCookielessRedisConnectionConfig(this.config),
                        poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                        poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                    })
                )
                // Dedicated $feature_flag_called dedup Redis, so its claim keys don't compete
                // with ingestion's overflow-redirect keys under eviction. Falls back to the
                // ingestion connection until the dedup host is configured.
                .add(
                    'featureFlagCalledDedupRedisPool',
                    new RedisPoolComponent({
                        connection: createFeatureFlagCalledDedupRedisConnectionConfig(this.config),
                        poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                        poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                    })
                )
                .add('producerRegistry', new KafkaProducerRegistryComponent(this.config.KAFKA_CLIENT_RACK, this.config))
        )

        // Services are built off the started infra scope (postgres, redis pools, kafka). They're
        // owned by this scope, so consumers can `Scope.extend` off it to read shared services like
        // the team manager and cookieless manager without taking ownership of their lifecycle.
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
                .add('cookielessManager', new CookielessManagerComponent(this.config, container.cookielessRedisPool))
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

        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub, this.postgres, encryptedFields)

        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        const isCombinedMode = this.config.PLUGIN_SERVER_MODE === PluginServerMode.ingestion_v2_combined

        // Producer registry is owned by `sharedInfraScope`; the
        // server reads it back from the started services. Outputs is
        // a typed view over it — built once here for analytics, and
        // separately by each consumer factory as needed.
        const ingestionProducerRegistry = sharedServices.container.producerRegistry
        const ingestionOutputs = createOutputsRegistry().build(ingestionProducerRegistry, this.config)

        const hogTransformerDeps: HogTransformerServiceDeps = {
            geoipService,
            postgres: this.postgres,
            pubSub: this.pubsub,
            encryptedFields,
            integrationManager,
            monitoringOutputs: ingestionOutputs,
            teamManager,
        }

        // The analytics lane can't construct the cdp-owned hog transformer itself (boundary),
        // so the server injects it (and the lane's outputs, which also back the transformer's
        // monitoring) through an analytics-specific scope. The personhog-routed person/group
        // repositories are injected here too — like legacy, they carry the personhog rollout and
        // are shared across combined-mode lanes. The consumer owns everything else (restriction
        // manager, event filters, overflow redirect, stores, tophog). In combined mode all three
        // analytics lanes extend this one scope, so — as before — they share a single hog
        // transformer, outputs, and repositories instance.
        const clientLabel = this.config.PLUGIN_SERVER_MODE ?? 'unknown'
        const analyticsSharedScope = extend(sharedServicesScope, 'analytics-shared', (container, builder) =>
            builder
                .add(
                    'hogTransformer',
                    new HogTransformerComponent(() => createHogTransformerService(this.config, hogTransformerDeps))
                )
                .add('outputs', new IngestionOutputsComponent(() => ingestionOutputs))
                .add(
                    'repositories',
                    new PersonHogRoutedRepositoriesComponent(this.config, container.postgres, clientLabel)
                )
        )

        const startAnalytics = (override?: { topic: string; groupId: string }) => {
            serviceLoaders.push(async () => {
                const consumerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumerScope = createAnalyticsConsumer(
                    consumerConfig,
                    analyticsSharedScope,
                    createAiEventSubpipeline
                )
                const { consumer, stop } = await consumerScope.start()
                return ingestionConsumerService(consumer, stop)
            })
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

        const startHeatmaps = (override?: { topic: string; groupId: string }) => {
            serviceLoaders.push(async () => {
                const consumerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                const consumerScope = createHeatmapsConsumer(consumerConfig, sharedServicesScope)
                const { consumer, stop } = await consumerScope.start()
                return ingestionConsumerService(consumer, stop)
            })
        }

        const startAi = (override?: { topic: string; groupId: string }) => {
            serviceLoaders.push(async () => {
                const consumerConfig = override
                    ? {
                          ...this.config,
                          INGESTION_CONSUMER_CONSUME_TOPIC: override.topic,
                          INGESTION_CONSUMER_GROUP_ID: override.groupId,
                      }
                    : this.config
                // The AI lane can't construct the cdp-owned hog transformer itself (boundary),
                // so the server injects it (and the lane's outputs, which also back the
                // transformer's monitoring) through an AI-specific scope. The consumer owns
                // everything else (incl. its personhog client), taking only config + parent scope.
                const aiOutputs = createAiOutputsRegistry().build(ingestionProducerRegistry, this.config)
                const aiSharedScope = extend(sharedServicesScope, 'ai-shared', (_container, builder) =>
                    builder
                        .add(
                            'hogTransformer',
                            new HogTransformerComponent(() =>
                                createHogTransformerService(this.config, {
                                    ...hogTransformerDeps,
                                    monitoringOutputs: aiOutputs,
                                })
                            )
                        )
                        .add('outputs', new IngestionOutputsComponent(() => aiOutputs))
                )
                const consumerScope = createAiConsumer(consumerConfig, aiSharedScope)
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
            ]

            for (const consumerOption of consumersOptions) {
                startAnalytics({ topic: consumerOption.topic, groupId: consumerOption.group_id })
            }

            startClientWarnings({
                topic: 'ingestion-clientwarnings-main-1',
                groupId: 'ingestion-clientwarnings-main',
            })

            startHeatmaps({
                topic: 'heatmaps_ingestion',
                groupId: 'heatmaps_ingestion',
            })
        } else if (this.config.INGESTION_PIPELINE === 'clientwarnings') {
            startClientWarnings()
        } else if (this.config.INGESTION_PIPELINE === 'heatmaps') {
            startHeatmaps()
        } else if (this.config.INGESTION_PIPELINE === 'ai') {
            // Dedicated AI pipeline deployment. Not started in combined mode: the
            // combined analytics consumers already process AI events on the shared
            // topic, so running this in parallel there would double-process them.
            // Switchover to this pipeline is driven by capture-side routing.
            startAi()
        } else {
            // Production ingestion-v2: single consumer using config-provided topic
            startAnalytics()
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
            redisPools: [],
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                if (this.stopSharedServices) {
                    await this.stopSharedServices()
                }
            },
        }
    }
}
