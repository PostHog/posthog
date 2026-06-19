import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import {
    AiEventOutput,
    AppMetricsOutput,
    DlqOutput,
    EventOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    ProducerName,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { createPersonHogClient } from '~/common/personhog'
import { PersonHogClient } from '~/common/personhog/client'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManagerComponent } from '~/ingestion/common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { Component, Scope, extend } from '~/ingestion/common/scopes'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { IngestionConsumerConfig, IngestionOutputsConfig, PersonHogConfig } from '~/ingestion/config'
import { parseSplitAiEventsConfig } from '~/ingestion/common/steps/event-processing/split-ai-events-step'
import { DisabledOverflowRedirect } from '~/ingestion/utils/overflow-redirect/disabled-overflow-redirect'
import { MainLaneOverflowRedirect } from '~/ingestion/utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '~/ingestion/utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '~/ingestion/utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '~/ingestion/utils/overflow-redirect/overflow-redis-repository'
import { RedisPool } from '~/types'
import { PostgresRouter } from '~/utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '~/utils/event-ingestion-restrictions'
import { TeamManager } from '~/utils/team-manager'

import { createAiIngestionPipeline } from './pipeline'

export type AiConsumerConfig = CommonIngestionConsumerConfig &
    IngestionOutputsConfig &
    PersonHogConfig &
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

/** Outputs the AI pipeline emits to. The same instance backs the hog transformer's
 * monitoring (app_metrics + log_entries), wired up server-side. */
export type AiOutputs = IngestionOutputs<
    EventOutput | AiEventOutput | IngestionWarningsOutput | DlqOutput | OverflowOutput | AppMetricsOutput
>

/**
 * Services shared from the server scope. Extends the base shared scope with the
 * hog transformer and outputs, which the server must build because the lane can't
 * construct the cdp-owned transformer (boundary) and the same outputs instance
 * backs the transformer's monitoring. The personhog client is owned by the AI
 * scope (created from common, tagged for this pipeline), not shared in here.
 */
export type AiSharedScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    cookielessManager: CookielessManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
    hogTransformer: HogTransformer
    outputs: AiOutputs
}>

/**
 * Wraps a hog transformer with start/stop lifecycle. The factory is supplied by
 * the server (the concrete `HogTransformerService` lives in cdp), so the AI scope
 * stays within ingestion boundaries while still owning the transformer's lifecycle.
 */
export function hogTransformerComponent(create: () => HogTransformer): Component<HogTransformer> {
    return {
        start: async () => {
            const hogTransformer = create()
            await hogTransformer.start()
            return { value: hogTransformer, stop: () => hogTransformer.stop() }
        },
    }
}

/**
 * Creates the personhog gRPC client for the AI lane. Built here (not injected) so
 * the connection is owned by the AI scope and torn down with it. Throws if
 * personhog isn't configured — the AI pipeline reads person/group data through it.
 */
function personhogClientComponent(config: PersonHogConfig): Component<PersonHogClient> {
    return {
        start: () => {
            const client = createPersonHogClient(config)
            if (!client) {
                throw new Error(
                    'PersonHog client is required for the AI ingestion pipeline — set PERSONHOG_ENABLED=true and PERSONHOG_ADDR'
                )
            }
            return Promise.resolve({
                value: client,
                stop: () => {
                    client.close()
                    return Promise.resolve()
                },
            })
        },
    }
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

export function createAiConsumer(config: AiConsumerConfig, sharedScope: AiSharedScope) {
    const splitTokens = (value: string): string[] => value.split(',').filter((x) => !!x)
    const overflowEnabled =
        !!config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
        config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== config.INGESTION_CONSUMER_CONSUME_TOPIC
    const overflowLaneEnabled = config.INGESTION_LANE === 'overflow' && config.INGESTION_STATEFUL_OVERFLOW_ENABLED
    const preservePartitionLocality = config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
    // Client name for personhog read metrics: pipeline + lane (e.g. "ai/main").
    // The query name is supplied per call (e.g. "person-properties").
    const clientLabel = `ai/${config.INGESTION_LANE ?? 'main'}`

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
            .add('overflowRedirectService', mainLaneOverflowComponent(container.redisPool, config, overflowEnabled))
            .add(
                'overflowLaneTTLRefreshService',
                overflowLaneComponent(container.redisPool, config, overflowLaneEnabled)
            )
            // Personhog client owned by the AI scope (created from common, torn down with it).
            .add('personhogClient', personhogClientComponent(config))
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
            // Read-only person/group access — read through personhog, never written.
            personRepository: new PersonHogPersonReadRepository(container.personhogClient, clientLabel),
            groupTypeManager: new ReadOnlyGroupTypeManager(
                new PersonHogGroupReadRepository(container.personhogClient, clientLabel)
            ),
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
