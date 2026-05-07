import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { CommonConfig } from '../../common/config'
import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { PersonRepository } from '../../worker/ingestion/persons/repositories/person-repository'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import {
    AppMetricsOutput,
    DlqOutput,
    GroupsOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    TophogOutput,
} from '../common/outputs'
import { IngestionConsumerConfig } from '../config'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { TopHog } from '../tophog'
import { MainLaneOverflowRedirect } from '../utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '../utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '../utils/overflow-redirect/overflow-redis-repository'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    HeatmapsOutput,
    PersonDistinctIdsOutput,
    PersonsOutput,
} from './outputs'
import { createAnalyticsPipeline } from './pipeline'

export type AnalyticsConsumerFullConfig = CommonIngestionConsumerConfig &
    Pick<
        IngestionConsumerConfig,
        | 'EVENT_SCHEMA_ENFORCEMENT_ENABLED'
        | 'INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
        | 'PERSONS_PREFETCH_ENABLED'
        | 'SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP'
        | 'PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT'
        | 'PERSON_MERGE_ASYNC_ENABLED'
        | 'PERSON_MERGE_SYNC_BATCH_SIZE'
        | 'PERSON_JSONB_SIZE_ESTIMATE_ENABLE'
        | 'PERSON_PROPERTIES_UPDATE_ALL'
    > &
    Pick<CommonConfig, 'CDP_HOG_WATCHER_SAMPLE_RATE'>

export interface AnalyticsConsumerDeps {
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | HeatmapsOutput
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | AsyncOutput
        | GroupsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | AppMetricsOutput
    >
    teamManager: TeamManager
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    cookielessManager: CookielessManager
    personsStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    topHog: TopHog
    overflowEnabled: boolean
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
}

function buildPerDistinctIdOptions(config: AnalyticsConsumerFullConfig): EventPipelineRunnerOptions {
    return {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        PERSON_MERGE_ASYNC_ENABLED: config.PERSON_MERGE_ASYNC_ENABLED,
        PERSON_MERGE_SYNC_BATCH_SIZE: config.PERSON_MERGE_SYNC_BATCH_SIZE,
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
        PERSON_PROPERTIES_UPDATE_ALL: config.PERSON_PROPERTIES_UPDATE_ALL,
    }
}

export function createAnalyticsConsumer(
    config: AnalyticsConsumerFullConfig,
    deps: AnalyticsConsumerDeps
): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .withService('eventFilterManager', deps.eventFilterManager)
        .withService('eventIngestionRestrictionManager', deps.eventIngestionRestrictionManager)
        .withService('eventSchemaEnforcementManager', deps.eventSchemaEnforcementManager)
        .withService('cookielessManager', deps.cookielessManager)
        .withService('personsStore', deps.personsStore)
        .withService('groupStore', deps.groupStore)
        .withService('groupTypeManager', deps.groupTypeManager)
        .withService('hogTransformer', deps.hogTransformer)
        .withService('topHog', deps.topHog)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createAnalyticsPipeline(
                {
                    eventSchemaEnforcementEnabled: config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
                    overflowEnabled: deps.overflowEnabled,
                    preservePartitionLocality: config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    personsPrefetchEnabled: config.PERSONS_PREFETCH_ENABLED,
                    cdpHogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
                    groupId: config.INGESTION_CONSUMER_GROUP_ID,
                    outputs,
                    perDistinctIdOptions: buildPerDistinctIdOptions(config),
                },
                {
                    ...services,
                    overflowRedirectService: deps.overflowRedirectService,
                    overflowLaneTTLRefreshService: deps.overflowLaneTTLRefreshService,
                    promiseScheduler,
                }
            )
        )
        .build()
}

/**
 * The full ingestion-server-flavored config for an analytics consumer instance —
 * a superset of `AnalyticsConsumerFullConfig` that adds the env vars consumed
 * by `assembleAnalyticsConsumer` while it constructs the per-consumer services.
 */
export type AnalyticsServerConfig = IngestionConsumerConfig &
    Pick<CommonConfig, 'KAFKA_CLIENT_RACK' | 'CDP_HOG_WATCHER_SAMPLE_RATE'>

/**
 * The base deps `assembleAnalyticsConsumer` accepts — postgres + redis + the
 * shared cross-consumer services plus the data-layer repositories. It builds
 * per-consumer instances of stores / managers / overflow services / topHog
 * before delegating to `createAnalyticsConsumer`.
 */
export interface AnalyticsServerDeps {
    postgres: PostgresRouter
    redisPool: RedisPool
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | HeatmapsOutput
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | AsyncOutput
        | GroupsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | AppMetricsOutput
        | TophogOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    cookielessManager: CookielessManager
    hogTransformer: HogTransformerService
}

function overflowEnabledFor(config: AnalyticsServerConfig): boolean {
    return (
        !!config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
        config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== config.INGESTION_CONSUMER_CONSUME_TOPIC
    )
}

/**
 * Construct the per-consumer instances of stores / managers / overflow services
 * / topHog from server-scoped deps. Exported separately from
 * `assembleAnalyticsConsumer` so tests can hold references to the constructed
 * services (for spying / asserting) and still share the construction logic with
 * production callers.
 */
export function buildAnalyticsConsumerDeps(
    config: AnalyticsServerConfig,
    deps: AnalyticsServerDeps
): AnalyticsConsumerDeps {
    const staticDropEventTokens = config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
    const staticSkipPersonTokens = config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
    const staticForceOverflowTokens = config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)

    const eventIngestionRestrictionManager = new EventIngestionRestrictionManager(deps.redisPool, {
        pipeline: 'analytics',
        staticDropEventTokens,
        staticSkipPersonTokens,
        staticForceOverflowTokens,
    })
    const eventFilterManager = new EventFilterManager(deps.postgres)
    const eventSchemaEnforcementManager = new EventSchemaEnforcementManager(deps.postgres)

    const overflowRedisRepository = new RedisOverflowRepository({
        redisPool: deps.redisPool,
        redisTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
    })

    const overflowEnabled = overflowEnabledFor(config)
    const overflowRedirectService: OverflowRedirectService | undefined = overflowEnabled
        ? new MainLaneOverflowRedirect({
              redisRepository: overflowRedisRepository,
              localCacheTTLSeconds: config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
              bucketCapacity: config.EVENT_OVERFLOW_BUCKET_CAPACITY,
              replenishRate: config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
              statefulEnabled: config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
          })
        : undefined
    const overflowLaneTTLRefreshService: OverflowRedirectService | undefined =
        config.INGESTION_LANE === 'overflow' && config.INGESTION_STATEFUL_OVERFLOW_ENABLED
            ? new OverflowLaneOverflowRedirect({ redisRepository: overflowRedisRepository })
            : undefined

    const personsStore = new BatchWritingPersonsStore(deps.personRepository, deps.outputs, {
        dbWriteMode: config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
        useBatchUpdates: config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
        maxConcurrentUpdates: config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
        maxOptimisticUpdateRetries: config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
        optimisticUpdateRetryInterval: config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        updateAllProperties: config.PERSON_PROPERTIES_UPDATE_ALL,
    })

    const groupStore = new BatchWritingGroupStore(deps.outputs, deps.groupRepository, deps.clickhouseGroupRepository, {
        maxConcurrentUpdates: config.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
        maxOptimisticUpdateRetries: config.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
        optimisticUpdateRetryInterval: config.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
    })

    const topHog = new TopHog({
        outputs: deps.outputs,
        pipeline: config.INGESTION_PIPELINE ?? 'unknown',
        lane: config.INGESTION_LANE ?? 'unknown',
    })

    return {
        outputs: deps.outputs,
        teamManager: deps.teamManager,
        eventFilterManager,
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        cookielessManager: deps.cookielessManager,
        personsStore,
        groupStore,
        groupTypeManager: deps.groupTypeManager,
        hogTransformer: deps.hogTransformer,
        topHog,
        overflowEnabled,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
    }
}

/**
 * Higher-level analytics consumer factory. Takes server-scoped deps + the full
 * ingestion config, constructs per-consumer instances of the managers / stores
 * / overflow services / topHog, then hands off to `createAnalyticsConsumer`.
 *
 * Use this from the ingestion server and from end-to-end tests; use the
 * lower-level `createAnalyticsConsumer` directly when the call site already has
 * everything constructed (e.g., the consumer-builder unit tests).
 */
export function assembleAnalyticsConsumer(
    config: AnalyticsServerConfig,
    deps: AnalyticsServerDeps
): CommonIngestionConsumer {
    return createAnalyticsConsumer(config, buildAnalyticsConsumerDeps(config, deps))
}
