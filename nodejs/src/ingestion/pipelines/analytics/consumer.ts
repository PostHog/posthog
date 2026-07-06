import { CommonConfig } from '~/common/config'
import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import {
    AiEventOutput,
    AppMetricsOutput,
    DlqOutput,
    EventOutput,
    GroupsOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
    TophogOutput,
} from '~/common/outputs'
import { AsyncOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig } from '~/common/personhog'
import { RoutedRepositories } from '~/common/personhog/personhog-routed-repositories-component'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManagerComponent } from '~/ingestion/common/event-filters'
import { createFeatureFlagCalledDedupService } from '~/ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { BatchWritingGroupStoreComponent } from '~/ingestion/common/groups/batch-writing-group-store'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { DisabledOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/disabled-overflow-redirect'
import { MainLaneOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/overflow-lane-overflow-redirect'
import { RedisOverflowRepositoryComponent } from '~/ingestion/common/overflow-redirect/overflow-redis-repository'
import { BatchWritingPersonsStoreComponent } from '~/ingestion/common/persons/batch-writing-person-store'
import { Scope, extend } from '~/ingestion/common/scopes'
import { AiEventSubpipelineFactory } from '~/ingestion/common/subpipelines/ai-subpipeline.contract'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { TopHogComponent } from '~/ingestion/framework/tophog'
import { RedisPool } from '~/types'

import { createJoinedIngestionPipeline } from './joined-ingestion-pipeline'

export type AnalyticsConsumerConfig = IngestionConsumerConfig &
    IngestionOutputsConfig &
    PersonHogConfig &
    CommonIngestionConsumerConfig &
    Pick<CommonConfig, 'CDP_HOG_WATCHER_SAMPLE_RATE'>

/** Outputs the analytics pipeline emits to. Server-built (the same instance backs the hog
 * transformer's monitoring) and injected through the shared scope. */
export type AnalyticsOutputs = IngestionOutputs<
    | EventOutput
    | AiEventOutput
    | IngestionWarningsOutput
    | DlqOutput
    | OverflowOutput
    | AsyncOutput
    | GroupsOutput
    | PersonsOutput
    | PersonDistinctIdsOutput
    | PersonMergeEventsOutput
    | AppMetricsOutput
    | TophogOutput
>

/**
 * Services shared from the server scope. Like the AI lane, the server injects the hog
 * transformer (the lane can't construct the cdp-owned transformer) and the outputs (the
 * same instance backs the transformer's monitoring). The personhog-routed person/group
 * repositories are also server-injected — like legacy, they carry the personhog rollout and
 * are shared across combined-mode lanes. The group-type and event-schema-enforcement managers
 * are shared here too so their `LazyLoader` caches warm once across lanes rather than per lane.
 * The analytics scope owns everything else: restriction manager, event filters, overflow
 * redirect, stores, tophog.
 */
export type AnalyticsSharedScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    featureFlagCalledDedupRedisPool: RedisPool
    teamManager: TeamManager
    cookielessManager: CookielessManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
    hogTransformer: HogTransformer
    outputs: AnalyticsOutputs
    repositories: RoutedRepositories
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    groupTypeManager: GroupTypeManager
}>

export function createAnalyticsConsumer(
    config: AnalyticsConsumerConfig,
    sharedScope: AnalyticsSharedScope,
    aiSubpipelineFactory: AiEventSubpipelineFactory,
    lane: string
) {
    const splitTokens = (value: string): string[] => value.split(',').filter((x) => !!x)
    const overflowEnabled =
        !!config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
        config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== config.INGESTION_CONSUMER_CONSUME_TOPIC
    const overflowLaneEnabled = config.INGESTION_LANE === 'overflow' && config.INGESTION_STATEFUL_OVERFLOW_ENABLED

    // Parent layer: the overflow Redis repository, shared by both redirect services below.
    const baseScope = extend(sharedScope, 'analytics-base', (container, builder) =>
        builder.add(
            'overflowRedisRepository',
            new RedisOverflowRepositoryComponent(
                container.redisPool,
                config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS
            )
        )
    )

    const scope = extend(baseScope, 'analytics', (container, builder) =>
        builder
            .add('promiseScheduler', new PromiseSchedulerComponent())
            .add(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerComponent(container.redisPool, {
                    pipeline: 'analytics',
                    staticDropEventTokens: splitTokens(config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
                    staticSkipPersonTokens: splitTokens(config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID),
                    staticForceOverflowTokens: splitTokens(config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID),
                })
            )
            .add('eventFilterManager', new EventFilterManagerComponent(container.postgres))
            .add(
                'overflowRedirectService',
                overflowEnabled
                    ? new MainLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          localCacheTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                          bucketCapacity: config.EVENT_OVERFLOW_BUCKET_CAPACITY,
                          replenishRate: config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
                          statefulEnabled: config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
                          overflowType: 'events',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            .add(
                'overflowLaneTTLRefreshService',
                overflowLaneEnabled
                    ? new OverflowLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          overflowType: 'events',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            .add(
                'topHog',
                new TopHogComponent({
                    outputs: container.outputs,
                    pipeline: config.INGESTION_PIPELINE ?? 'unknown',
                    lane: config.INGESTION_LANE ?? 'unknown',
                })
            )
            .add(
                'personsStore',
                new BatchWritingPersonsStoreComponent(container.repositories.personRepository, container.outputs, {
                    dbWriteMode: config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
                    useBatchUpdates: config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
                    maxConcurrentUpdates: config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
                    maxOptimisticUpdateRetries: config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
                    optimisticUpdateRetryInterval: config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
                    updateAllProperties: config.PERSON_PROPERTIES_UPDATE_ALL,
                })
            )
            .add(
                'groupStore',
                new BatchWritingGroupStoreComponent(
                    container.outputs,
                    container.repositories.groupRepository,
                    new ClickhouseGroupRepository(container.outputs),
                    {
                        maxConcurrentUpdates: config.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
                        maxOptimisticUpdateRetries: config.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
                        optimisticUpdateRetryInterval: config.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
                    }
                )
            )
    )

    return new CommonIngestionConsumerScope('analytics', lane, config, scope, ({ container }) =>
        createJoinedIngestionPipeline(
            {
                eventSchemaEnforcementEnabled: config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
                overflowEnabled,
                preservePartitionLocality: config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                personsPrefetchEnabled: config.PERSONS_PREFETCH_ENABLED,
                cdpHogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
                outputs: container.outputs,
                perDistinctIdOptions: {
                    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                    PERSON_MERGE_ASYNC_ENABLED: config.PERSON_MERGE_ASYNC_ENABLED,
                    PERSON_MERGE_SYNC_BATCH_SIZE: config.PERSON_MERGE_SYNC_BATCH_SIZE,
                    PERSON_MERGE_EVENTS_ENABLED: config.PERSON_MERGE_EVENTS_ENABLED,
                    PERSON_MERGE_EVENTS_PARTITION_COUNT: config.PERSON_MERGE_EVENTS_PARTITION_COUNT,
                    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                    PERSON_PROPERTIES_UPDATE_ALL: config.PERSON_PROPERTIES_UPDATE_ALL,
                    FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: config.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
                },
                concurrentBatches: config.INGESTION_WORKER_CONCURRENT_BATCHES,
            },
            {
                personsStore: container.personsStore,
                groupStore: container.groupStore,
                hogTransformer: container.hogTransformer,
                aiSubpipelineFactory,
                eventFilterManager: container.eventFilterManager,
                eventIngestionRestrictionManager: container.eventIngestionRestrictionManager,
                eventSchemaEnforcementManager: container.eventSchemaEnforcementManager,
                promiseScheduler: container.promiseScheduler,
                overflowRedirectService: container.overflowRedirectService,
                overflowLaneTTLRefreshService: container.overflowLaneTTLRefreshService,
                featureFlagCalledDedupService: createFeatureFlagCalledDedupService(
                    container.featureFlagCalledDedupRedisPool,
                    config
                ),
                teamManager: container.teamManager,
                cookielessManager: container.cookielessManager,
                groupTypeManager: container.groupTypeManager,
                topHog: container.topHog,
            }
        )
    )
}
