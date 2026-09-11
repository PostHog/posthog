import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '~/common/config/redis-pools'
import { HogTransformerComponent } from '~/common/hog-transformations/hog-transformer-component'
import { IngestionOutputsComponent } from '~/common/outputs/ingestion-outputs'
import { PersonHogConfig } from '~/common/personhog'
import { UsageIngestionConfig } from '~/common/usage-ingestion'
import { ServerCommands } from '~/common/utils/commands'
import { PostgresRouter, PostgresRouterComponent } from '~/common/utils/db/postgres'
import { RedisPoolComponent } from '~/common/utils/db/redis'
import { GeoIPService } from '~/common/utils/geoip'
import { DEFAULT_LOADER_RETRY } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManagerComponent } from '~/common/utils/team-manager'
import { CookielessManagerComponent, CookielessServerConfig } from '~/ingestion/common/cookieless/cookieless-manager'
import { ingestionConsumerService } from '~/ingestion/common/ingestion-consumer'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import {
    KafkaDownstreamProducerEnvConfig,
    KafkaUpstreamProducerEnvConfig,
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { extend, newScope } from '~/ingestion/common/scopes'
import {
    ErrorTrackingConsumerConfig,
    ErrorTrackingOutputsConfig,
    getDefaultErrorTrackingConsumerConfig,
    getDefaultErrorTrackingOutputsConfig,
} from '~/ingestion/pipelines/errortracking/config'
import { createErrorTrackingConsumer } from '~/ingestion/pipelines/errortracking/consumer'
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
    IngestionConsumerConfig,
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
 * - HogTransformerServiceConfig: the transformation-only keys the in-process hog transformer reads.
 *   No CDP delivery config (Redis, watcher, SES, fetch) - transformations run the synchronous
 *   Hog core alone, so those keys are deliberately absent rather than inherited.
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
    UsageIngestionConfig &
    CookielessServerConfig &
    Pick<IngestionConsumerConfig, 'KAFKA_BATCH_START_LOGGING_ENABLED'> &
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'ENCRYPTION_SALT_KEYS'
        | 'MMDB_FILE_LOCATION'
        | 'CAPTURE_INTERNAL_URL'
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class ErrorTrackingServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: ErrorTrackingServerConfig

    private postgres?: PostgresRouter
    private redisPool?: RedisPool
    private pubsub?: PubSub
    private stopSharedServices?: () => Promise<void>

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

        // 1. Shared infrastructure — postgres, redis pools and the producer registry are
        //    owned by a server-level Scope so the consumer can extend off it to get them
        //    as handles without taking ownership.
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
                .add(
                    'cookielessRedisPool',
                    new RedisPoolComponent({
                        connection: createCookielessRedisConnectionConfig(this.config),
                        poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                        poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                    })
                )
                .add('producerRegistry', new KafkaProducerRegistryComponent(this.config.KAFKA_CLIENT_RACK, this.config))
        )

        const sharedServicesScope = extend(sharedInfraScope, 'shared', (container, builder) =>
            builder
                .add(
                    'teamManager',
                    // Retry transient team-load failures (e.g. a Postgres pooler scale-down returning
                    // ECONNREFUSED). The team loader runs detached in the LazyLoader buffer, so an un-retried
                    // transient failure can surface as an unhandled rejection and restart the worker.
                    new TeamManagerComponent(container.postgres, { loaderRetry: DEFAULT_LOADER_RETRY })
                )
                .add('cookielessManager', new CookielessManagerComponent(this.config, container.cookielessRedisPool))
        )

        const sharedServices = await sharedServicesScope.start()
        this.postgres = sharedServices.container.postgres
        this.redisPool = sharedServices.container.redisPool
        this.stopSharedServices = sharedServices.stop
        logger.info('👍', 'Postgres Router ready')
        logger.info('👍', 'Kafka ready')
        logger.info('👍', 'Ingestion Redis ready')
        logger.info('👍', 'Cookieless Redis ready')

        this.pubsub = new PubSub(this.redisPool)
        await this.pubsub.start()

        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()

        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(this.pubsub, this.postgres, encryptedFields)

        // The same outputs instance backs the pipeline's emissions and the hog
        // transformer's monitoring (app_metrics + log_entries).
        const outputs = createOutputsRegistry().build(sharedServices.container.producerRegistry, this.config)

        const hogTransformerDeps: HogTransformerServiceDeps = {
            geoipService,
            postgres: this.postgres,
            pubSub: this.pubsub,
            encryptedFields,
            integrationManager,
            monitoringOutputs: outputs,
        }

        const errorTrackingSharedScope = extend(sharedServicesScope, 'errortracking-shared', (_container, builder) =>
            builder
                .add(
                    'hogTransformer',
                    new HogTransformerComponent(() => createHogTransformerService(this.config, hogTransformerDeps))
                )
                .add('outputs', new IngestionOutputsComponent(() => outputs))
        )

        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumerScope = createErrorTrackingConsumer(
                {
                    ...this.config,
                    INGESTION_CONSUMER_GROUP_ID: this.config.ERROR_TRACKING_CONSUMER_GROUP_ID,
                    INGESTION_CONSUMER_CONSUME_TOPIC: this.config.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
                },
                errorTrackingSharedScope
            )
            const { consumer, stop } = await consumerScope.start()
            return ingestionConsumerService(consumer, stop)
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
