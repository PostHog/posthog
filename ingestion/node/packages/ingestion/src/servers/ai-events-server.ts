import { createHogTransformerService } from '@posthog/hog-engine/cdp/hog-transformations/hog-transformer.service'
import { IntegrationManagerService } from '@posthog/hog-engine/cdp/services/managers/integration-manager.service'
import { PostgresIntegrationSource } from '@posthog/hog-engine/cdp/services/managers/postgres-integration-source'
import { EncryptedFields } from '@posthog/hog-engine/cdp/utils/encryption-utils'
import {
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '@posthog/ingestion-common/outputs/producers'
import { extend, newScope } from '@posthog/ingestion-common/scopes/index'
import { initializePrometheusLabels } from '@posthog/node-common/api/router'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '@posthog/node-common/config/redis-pools'
import { HogTransformerComponent } from '@posthog/node-common/hog-transformations/hog-transformer-component'
import { IngestionOutputsComponent } from '@posthog/node-common/outputs/ingestion-outputs'
import { CleanupResources, NodeServer, ServerLifecycle } from '@posthog/node-common/servers/base-server'
import { ServerCommands } from '@posthog/node-common/utils/commands'
import { PostgresRouter, PostgresRouterComponent } from '@posthog/node-common/utils/db/postgres'
import { RedisPoolComponent } from '@posthog/node-common/utils/db/redis'
import { GeoIPService } from '@posthog/node-common/utils/geoip'
import { DEFAULT_LOADER_RETRY } from '@posthog/node-common/utils/lazy-loader'
import { logger } from '@posthog/node-common/utils/logger'
import { PubSub } from '@posthog/node-common/utils/pubsub'
import { TeamManagerComponent } from '@posthog/node-common/utils/team-manager'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { CookielessManagerComponent } from '~/ingestion/common/cookieless/cookieless-manager'
import { ingestionConsumerService } from '~/ingestion/common/ingestion-consumer'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import { getDefaultIngestionConsumerConfig, getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import { createAiConsumer } from '~/ingestion/pipelines/ai'
import { createOutputsRegistry as createAiOutputsRegistry } from '~/ingestion/pipelines/ai/outputs/registry'

import { RedisPool } from '../types'
import { IngestionGeneralServerConfig } from './ingestion-general-server'

/**
 * The AI events consumer as a server of its own, so that its code and its deployments stand apart
 * from the analytics pipeline. It reads the same configuration as the general server.
 */
export class AiEventsServer implements NodeServer {
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
        initializePrometheusLabels('ai', this.config.INGESTION_LANE)
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
                .add('teamManager', new TeamManagerComponent(container.postgres, { loaderRetry: DEFAULT_LOADER_RETRY }))
                .add('cookielessManager', new CookielessManagerComponent(this.config, container.cookielessRedisPool))
        )
        const sharedServices = await sharedServicesScope.start()
        this.postgres = sharedServices.container.postgres
        this.redisPool = sharedServices.container.redisPool
        this.stopSharedServices = sharedServices.stop
        logger.info('👍', 'Postgres Router ready')
        logger.info('👍', 'Ingestion Redis ready')

        this.pubsub = new PubSub(this.redisPool)
        await this.pubsub.start()

        const geoipService = new GeoIPService(this.config.MMDB_FILE_LOCATION)
        await geoipService.get()
        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        const integrationManager = new IntegrationManagerService(
            this.pubsub,
            new PostgresIntegrationSource(this.postgres, encryptedFields)
        )

        // The consumer cannot construct the CDP-owned hog transformer itself, so the server injects it
        // and the lane's outputs, which also back the transformer's monitoring, through this scope.
        const aiOutputs = createAiOutputsRegistry().build(sharedServices.container.producerRegistry, this.config)
        const aiSharedScope = extend(sharedServicesScope, 'ai-shared', (_container, builder) =>
            builder
                .add(
                    'hogTransformer',
                    new HogTransformerComponent(() =>
                        createHogTransformerService(this.config, {
                            geoipService,
                            postgres: this.postgres!,
                            pubSub: this.pubsub!,
                            encryptedFields,
                            integrationManager,
                            monitoringOutputs: aiOutputs,
                            teamManager: sharedServices.container.teamManager,
                        })
                    )
                )
                .add('outputs', new IngestionOutputsComponent(() => aiOutputs))
        )
        const { consumer, stop } = await createAiConsumer(this.config, aiSharedScope).start()

        const serverCommands = new ServerCommands(this.pubsub)
        this.lifecycle.expressApp.use('/', serverCommands.router())
        this.lifecycle.services.push(ingestionConsumerService(consumer, stop), serverCommands.service)
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
