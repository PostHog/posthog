import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { CommonConfig } from '../../common/config'
import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { PersonRepository } from '../../worker/ingestion/persons/repositories/person-repository'
import { HeatmapsOutput, PersonDistinctIdsOutput, PersonsOutput } from '../analytics/outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import { IngestionConsumerConfig } from '../config'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { HeatmapEventOptions } from './heatmap-subpipeline'
import { createHeatmapsPipeline } from './pipeline'

export type HeatmapsConsumerFullConfig = CommonIngestionConsumerConfig &
    Pick<
        IngestionConsumerConfig,
        | 'INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
        | 'PERSONS_PREFETCH_ENABLED'
        | 'SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP'
    > &
    Pick<CommonConfig, 'CDP_HOG_WATCHER_SAMPLE_RATE'>

export interface HeatmapsConsumerDeps {
    outputs: IngestionOutputs<
        | HeatmapsOutput
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | GroupsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | AppMetricsOutput
    >
    teamManager: TeamManager
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    cookielessManager: CookielessManager
    personsStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
}

function buildPerEventOptions(config: HeatmapsConsumerFullConfig): HeatmapEventOptions {
    return {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
    }
}

export function createHeatmapsConsumer(
    config: HeatmapsConsumerFullConfig,
    deps: HeatmapsConsumerDeps
): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .withService('eventFilterManager', deps.eventFilterManager)
        .withService('eventIngestionRestrictionManager', deps.eventIngestionRestrictionManager)
        .withService('cookielessManager', deps.cookielessManager)
        .withService('personsStore', deps.personsStore)
        .withService('groupStore', deps.groupStore)
        .withService('groupTypeManager', deps.groupTypeManager)
        .withService('hogTransformer', deps.hogTransformer)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createHeatmapsPipeline(
                {
                    preservePartitionLocality: config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    personsPrefetchEnabled: config.PERSONS_PREFETCH_ENABLED,
                    cdpHogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
                    outputs,
                    perEventOptions: buildPerEventOptions(config),
                },
                {
                    ...services,
                    promiseScheduler,
                }
            )
        )
        .build()
}

/**
 * The full ingestion-server-flavored config for a heatmaps consumer instance —
 * a superset of `HeatmapsConsumerFullConfig` that adds the env vars consumed
 * by `assembleHeatmapsConsumer` while it constructs the per-consumer services.
 *
 * No overflow / no schema-enforcement keys: the heatmaps pipeline doesn't run
 * those steps.
 */
export type HeatmapsServerConfig = HeatmapsConsumerFullConfig &
    Pick<
        IngestionConsumerConfig,
        | 'DROP_EVENTS_BY_TOKEN_DISTINCT_ID'
        | 'SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID'
        | 'INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID'
        | 'PERSON_BATCH_WRITING_DB_WRITE_MODE'
        | 'PERSON_BATCH_WRITING_USE_BATCH_UPDATES'
        | 'PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES'
        | 'PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES'
        | 'PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS'
        | 'PERSON_PROPERTIES_UPDATE_ALL'
        | 'GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES'
        | 'GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES'
        | 'GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS'
    >

/**
 * Server-scoped deps that `assembleHeatmapsConsumer` needs to construct the
 * per-consumer services (eventFilterManager, eventIngestionRestrictionManager,
 * personsStore, groupStore). Caller-supplied: postgres + redis + repositories
 * + already-constructed cross-consumer services.
 */
export interface HeatmapsServerDeps {
    postgres: PostgresRouter
    redisPool: RedisPool
    outputs: HeatmapsConsumerDeps['outputs']
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    cookielessManager: CookielessManager
    hogTransformer: HogTransformerService
}

export function buildHeatmapsConsumerDeps(
    config: HeatmapsServerConfig,
    deps: HeatmapsServerDeps
): HeatmapsConsumerDeps {
    const eventIngestionRestrictionManager = new EventIngestionRestrictionManager(deps.redisPool, {
        pipeline: 'analytics',
        staticDropEventTokens: config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x),
        staticSkipPersonTokens: config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x),
        staticForceOverflowTokens: config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x),
    })
    const eventFilterManager = new EventFilterManager(deps.postgres)

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

    return {
        outputs: deps.outputs,
        teamManager: deps.teamManager,
        eventFilterManager,
        eventIngestionRestrictionManager,
        cookielessManager: deps.cookielessManager,
        personsStore,
        groupStore,
        groupTypeManager: deps.groupTypeManager,
        hogTransformer: deps.hogTransformer,
    }
}

/**
 * Higher-level heatmaps consumer factory: takes server-scoped deps + the full
 * ingestion config, builds per-consumer services, and hands off to
 * `createHeatmapsConsumer`. Use from the ingestion server / e2e tests.
 */
export function assembleHeatmapsConsumer(
    config: HeatmapsServerConfig,
    deps: HeatmapsServerDeps
): CommonIngestionConsumer {
    return createHeatmapsConsumer(config, buildHeatmapsConsumerDeps(config, deps))
}
