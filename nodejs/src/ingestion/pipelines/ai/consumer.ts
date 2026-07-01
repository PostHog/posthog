import { CommonConfig } from '~/common/config'
import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import {
    AiEventOutput,
    AppMetricsOutput,
    DlqOutput,
    EventOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    TophogOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig } from '~/common/personhog'
import { PersonHogClientComponent } from '~/common/personhog/personhog-client-component'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManagerComponent } from '~/ingestion/common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { ProducerName } from '~/ingestion/common/producers'
import { Scope, extend } from '~/ingestion/common/scopes'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { TopHog } from '~/ingestion/framework/tophog'
import { DisabledOverflowRedirectComponent } from '~/ingestion/utils/overflow-redirect/disabled-overflow-redirect'
import { MainLaneOverflowRedirectComponent } from '~/ingestion/utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirectComponent } from '~/ingestion/utils/overflow-redirect/overflow-lane-overflow-redirect'
import { RedisOverflowRepositoryComponent } from '~/ingestion/utils/overflow-redirect/overflow-redis-repository'
import { RedisPool } from '~/types'

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
        | 'DROP_EVENTS_BY_TOKEN_DISTINCT_ID'
        | 'SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID'
        | 'INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID'
        | 'EVENT_SCHEMA_ENFORCEMENT_ENABLED'
    > &
    Pick<CommonConfig, 'CDP_HOG_WATCHER_SAMPLE_RATE'>

/** Outputs the AI pipeline emits to. The same instance backs the hog transformer's
 * monitoring (app_metrics + log_entries), wired up server-side. */
export type AiOutputs = IngestionOutputs<
    EventOutput | AiEventOutput | IngestionWarningsOutput | DlqOutput | OverflowOutput | AppMetricsOutput | TophogOutput
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

    // Parent scope: the overflow Redis repository, shared by the main-lane and
    // overflow-lane redirect services below (set up here, not inline per service).
    const overflowScope = extend(sharedScope, 'ai-overflow', (container, builder) =>
        builder.add(
            'overflowRedisRepository',
            new RedisOverflowRepositoryComponent(
                container.redisPool,
                config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS
            )
        )
    )

    const scope = extend(overflowScope, 'ai', (container, builder) =>
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
            // Dedicated 'ai' keyspace so AI overflow never affects analytics.
            .add(
                'overflowRedirectService',
                overflowEnabled
                    ? new MainLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          localCacheTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                          bucketCapacity: config.EVENT_OVERFLOW_BUCKET_CAPACITY,
                          replenishRate: config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
                          statefulEnabled: config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
                          overflowType: 'ai',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            .add(
                'overflowLaneTTLRefreshService',
                overflowLaneEnabled
                    ? new OverflowLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          overflowType: 'ai',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            // Personhog client owned by the AI scope (created from common, torn down with it).
            .add('personhogClient', new PersonHogClientComponent(config))
            // TopHog metrics registry for this lane's outputs (drains per-team/partition counters).
            .add('topHog', {
                start: () => {
                    const topHog = new TopHog({
                        outputs: container.outputs,
                        pipeline: config.INGESTION_PIPELINE ?? 'unknown',
                        lane: config.INGESTION_LANE ?? 'unknown',
                    })
                    topHog.start()
                    return Promise.resolve({ value: topHog, stop: () => topHog.stop() })
                },
            })
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
            overflowEnabled,
            preservePartitionLocality,
            overflowRedirectService: container.overflowRedirectService,
            overflowLaneTTLRefreshService: container.overflowLaneTTLRefreshService,
            concurrentBatches: config.INGESTION_WORKER_CONCURRENT_BATCHES,
            cdpHogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
            eventSchemaEnforcementEnabled: config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
            eventSchemaEnforcementManager: new EventSchemaEnforcementManager(container.postgres),
            topHog: createTopHogWrapper(container.topHog),
        })
    )
}
