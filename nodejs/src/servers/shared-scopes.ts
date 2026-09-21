import { CommonConfig } from '~/common/config'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '~/common/config/redis-pools'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter, PostgresRouterComponent } from '~/common/utils/db/postgres'
import { RedisConnectionConfig, RedisPoolComponent } from '~/common/utils/db/redis'
import { DEFAULT_LOADER_RETRY } from '~/common/utils/lazy-loader'
import { TeamManager, TeamManagerComponent } from '~/common/utils/team-manager'
import {
    CookielessManager,
    CookielessManagerComponent,
    CookielessServerConfig,
} from '~/ingestion/common/cookieless/cookieless-manager'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import {
    KafkaDownstreamProducerEnvConfig,
    KafkaUpstreamProducerEnvConfig,
    ProducerName,
} from '~/ingestion/common/outputs/producers'
import { ScopeBuilder } from '~/ingestion/common/scopes'
import { DatabaseConnectionConfig, KafkaBrokerConfig, RedisConnectionsConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'

export type SharedInfraConfig = DatabaseConnectionConfig &
    RedisConnectionsConfig &
    CookielessServerConfig &
    KafkaBrokerConfig &
    KafkaUpstreamProducerEnvConfig &
    KafkaDownstreamProducerEnvConfig &
    Pick<CommonConfig, 'PLUGIN_SERVER_MODE'>

export type SharedInfra = {
    postgres: PostgresRouter
    redisPool: RedisPool
    cookielessRedisPool: RedisPool
    producerRegistry: KafkaProducerRegistry<ProducerName>
}

export type SharedServices = {
    teamManager: TeamManager
    cookielessManager: CookielessManager
}

export function addSharedInfra(
    builder: ScopeBuilder<Record<never, object>>,
    config: SharedInfraConfig
): ScopeBuilder<SharedInfra> {
    const redisPool = (connection: RedisConnectionConfig): RedisPoolComponent =>
        new RedisPoolComponent({
            connection,
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })

    // Cookieless Redis is a separate pool, shared by every consumer that runs cookieless
    // processing (analytics, heatmaps, error tracking, …).
    return builder
        .add('postgres', new PostgresRouterComponent(config, config.PLUGIN_SERVER_MODE!))
        .add('redisPool', redisPool(createIngestionRedisConnectionConfig(config)))
        .add('cookielessRedisPool', redisPool(createCookielessRedisConnectionConfig(config)))
        .add('producerRegistry', new KafkaProducerRegistryComponent(config.KAFKA_CLIENT_RACK, config))
}

export function addSharedServices(
    infra: Pick<SharedInfra, 'postgres' | 'cookielessRedisPool'>,
    builder: ScopeBuilder<Record<never, object>>,
    config: CookielessServerConfig
): ScopeBuilder<SharedServices> {
    return builder
        .add(
            'teamManager',
            // Retry transient team-load failures (e.g. a Postgres pooler scale-down returning
            // ECONNREFUSED). The team loader runs detached in the LazyLoader buffer, so an un-retried
            // transient failure can surface as an unhandled rejection and restart the worker.
            new TeamManagerComponent(infra.postgres, { loaderRetry: DEFAULT_LOADER_RETRY })
        )
        .add('cookielessManager', new CookielessManagerComponent(config, infra.cookielessRedisPool))
}
