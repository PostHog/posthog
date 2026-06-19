import { CommonConfig } from '~/common/config'
import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { ProducerName } from '~/common/outputs'
import { IngestionOutputsComponent } from '~/common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogClient } from '~/common/personhog/client'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManagerComponent } from '~/ingestion/common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { Component, Scope, extend } from '~/ingestion/common/scopes'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { parseSplitAiEventsConfig } from '~/ingestion/steps/event-processing/split-ai-events-step'
import { DisabledOverflowRedirect } from '~/ingestion/utils/overflow-redirect/disabled-overflow-redirect'
import { MainLaneOverflowRedirect } from '~/ingestion/utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '~/ingestion/utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '~/ingestion/utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '~/ingestion/utils/overflow-redirect/overflow-redis-repository'
import { RedisPool } from '~/types'
import { PostgresRouter } from '~/utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '~/utils/event-ingestion-restrictions'
import { TeamManager } from '~/utils/team-manager'

import { createOutputsRegistry } from './outputs/registry'
import { createAiIngestionPipeline } from './pipeline'

export type AiConsumerConfig = CommonIngestionConsumerConfig &
    IngestionOutputsConfig &
    Pick<CommonConfig, 'PLUGIN_SERVER_MODE'> &
    Pick<
        IngestionConsumerConfig,
        | 'INGESTION_CONSUMER_OVERFLOW_TOPIC'
        | 'INGESTION_STATEFUL_OVERFLOW_ENABLED'
        | 'INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS'
        | 'INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS'
        | 'EVENT_OVERFLOW_BUCKET_CAPACITY'
        | 'EVENT_OVERFLOW_BUCKET_REPLENISH_RATE'
        | 'INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
        | 'INGESTION_WORKER_CONCURRENT_BATCHES'
        | 'INGESTION_AI_EVENT_SPLITTING_ENABLED'
        | 'INGESTION_AI_EVENT_SPLITTING_TEAMS'
        | 'INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY_TEAMS'
        | 'INGESTION_AI_EVENT_SPLITTING_PERCENTAGE'
        | 'DROP_EVENTS_BY_TOKEN_DISTINCT_ID'
        | 'SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID'
        | 'INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID'
    >

/** Services shared from the server scope (same shape as the heatmaps shared scope). */
export type AiSharedScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    cookielessManager: CookielessManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
}>

/**
 * Heavy, server-built services injected per consumer. The hog transformer's
 * concrete implementation needs server-level deps (geoip, pubsub, integration
 * manager), so the server builds it and injects it via the `HogTransformer`
 * interface. The personhog client is the shared gRPC connection; the AI
 * pipeline's read-only person/group repositories are built from it here.
 */
export interface AiConsumerDeps {
    hogTransformer: HogTransformer
    personhogClient: PersonHogClient | null
}

/** Builds the main-lane overflow redirect (rate-limiting) for the 'ai' keyspace. */
function mainLaneOverflowComponent(
    redisPool: RedisPool,
    config: AiConsumerConfig,
    enabled: boolean
): Component<OverflowRedirectService> {
    return {
        start: () => {
            const service: OverflowRedirectService = enabled
                ? new MainLaneOverflowRedirect({
                      redisRepository: new RedisOverflowRepository({
                          redisPool,
                          redisTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
                      }),
                      localCacheTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                      bucketCapacity: config.EVENT_OVERFLOW_BUCKET_CAPACITY,
                      replenishRate: config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
                      statefulEnabled: config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
                      // Dedicated 'ai' keyspace so AI overflow never affects analytics.
                      overflowType: 'ai',
                  })
                : new DisabledOverflowRedirect()
            return Promise.resolve({ value: service, stop: () => service.shutdown() })
        },
    }
}

/** Builds the overflow-lane TTL refresh service for the 'ai' keyspace. */
function overflowLaneComponent(
    redisPool: RedisPool,
    config: AiConsumerConfig,
    enabled: boolean
): Component<OverflowRedirectService> {
    return {
        start: () => {
            const service: OverflowRedirectService = enabled
                ? new OverflowLaneOverflowRedirect({
                      redisRepository: new RedisOverflowRepository({
                          redisPool,
                          redisTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
                      }),
                      overflowType: 'ai',
                  })
                : new DisabledOverflowRedirect()
            return Promise.resolve({ value: service, stop: () => service.shutdown() })
        },
    }
}

/** Wraps a hog transformer (built at the server level) with start/stop lifecycle. */
function hogTransformerComponent(hogTransformer: HogTransformer): Component<HogTransformer> {
    return {
        start: async () => {
            await hogTransformer.start()
            return { value: hogTransformer, stop: () => hogTransformer.stop() }
        },
    }
}

export function createAiConsumer(config: AiConsumerConfig, sharedScope: AiSharedScope, deps: AiConsumerDeps) {
    const personhogClient = deps.personhogClient
    if (!personhogClient) {
        throw new Error(
            'PersonHog client is required for the AI ingestion pipeline — set PERSONHOG_ENABLED=true and PERSONHOG_ADDR'
        )
    }

    const splitTokens = (value: string): string[] => value.split(',').filter((x) => !!x)
    const overflowEnabled =
        !!config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
        config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== config.INGESTION_CONSUMER_CONSUME_TOPIC
    const overflowLaneEnabled = config.INGESTION_LANE === 'overflow' && config.INGESTION_STATEFUL_OVERFLOW_ENABLED
    const preservePartitionLocality = config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
    const clientLabel = config.PLUGIN_SERVER_MODE ?? 'ai'

    const scope = extend(sharedScope, 'ai', (container, builder) =>
        builder
            .add('promiseScheduler', new PromiseSchedulerComponent())
            .add(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerComponent(container.redisPool, {
                    pipeline: 'ai',
                    staticDropEventTokens: splitTokens(config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
                    staticSkipPersonTokens: splitTokens(config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID),
                    staticForceOverflowTokens: splitTokens(config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID),
                })
            )
            .add('eventFilterManager', new EventFilterManagerComponent(container.postgres))
            .add(
                'outputs',
                new IngestionOutputsComponent(() => createOutputsRegistry().build(container.producerRegistry, config))
            )
            .add('hogTransformer', hogTransformerComponent(deps.hogTransformer))
            .add('overflowRedirectService', mainLaneOverflowComponent(container.redisPool, config, overflowEnabled))
            .add(
                'overflowLaneTTLRefreshService',
                overflowLaneComponent(container.redisPool, config, overflowLaneEnabled)
            )
            // Read-only person/group access — the AI pipeline reads person/group data
            // through personhog but never writes it.
            .add('personRepository', valueComponent(new PersonHogPersonReadRepository(personhogClient, clientLabel)))
            .add(
                'groupTypeManager',
                valueComponent(
                    new ReadOnlyGroupTypeManager(new PersonHogGroupReadRepository(personhogClient, clientLabel))
                )
            )
    )

    return new CommonIngestionConsumerScope('ai', config, scope, ({ container }) =>
        createAiIngestionPipeline({
            outputs: container.outputs,
            teamManager: container.teamManager,
            eventIngestionRestrictionManager: container.eventIngestionRestrictionManager,
            eventFilterManager: container.eventFilterManager,
            cookielessManager: container.cookielessManager,
            promiseScheduler: container.promiseScheduler,
            hogTransformer: container.hogTransformer,
            personRepository: container.personRepository,
            groupTypeManager: container.groupTypeManager,
            splitAiEventsConfig: parseSplitAiEventsConfig(
                config.INGESTION_AI_EVENT_SPLITTING_ENABLED,
                config.INGESTION_AI_EVENT_SPLITTING_TEAMS,
                config.INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY_TEAMS,
                config.INGESTION_AI_EVENT_SPLITTING_PERCENTAGE
            ),
            overflowEnabled,
            preservePartitionLocality,
            overflowRedirectService: container.overflowRedirectService,
            overflowLaneTTLRefreshService: container.overflowLaneTTLRefreshService,
            concurrentBatches: config.INGESTION_WORKER_CONCURRENT_BATCHES,
        })
    )
}

/** Adds an already-constructed, lifecycle-free value to the scope container. */
function valueComponent<T extends object>(value: T): Component<T> {
    return { start: () => Promise.resolve({ value, stop: () => Promise.resolve() }) }
}
