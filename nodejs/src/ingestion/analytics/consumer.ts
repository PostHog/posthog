import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { CommonConfig } from '../../common/config'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import { IngestionConsumerConfig } from '../config'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { TopHog } from '../tophog'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
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
