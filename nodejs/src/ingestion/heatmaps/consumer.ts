import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { CommonConfig } from '../../common/config'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { HeatmapsOutput, PersonDistinctIdsOutput, PersonsOutput } from '../analytics/outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import { IngestionConsumerConfig } from '../config'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { HeatmapEventOptions } from './heatmap-subpipeline'
import { createHeatmapsPipeline } from './pipeline'

export type HeatmapsConsumerFullConfig = CommonIngestionConsumerConfig &
    Pick<
        IngestionConsumerConfig,
        | 'EVENT_SCHEMA_ENFORCEMENT_ENABLED'
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
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    cookielessManager: CookielessManager
    personsStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    overflowEnabled: boolean
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
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
        .withService('eventSchemaEnforcementManager', deps.eventSchemaEnforcementManager)
        .withService('cookielessManager', deps.cookielessManager)
        .withService('personsStore', deps.personsStore)
        .withService('groupStore', deps.groupStore)
        .withService('groupTypeManager', deps.groupTypeManager)
        .withService('hogTransformer', deps.hogTransformer)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createHeatmapsPipeline(
                {
                    eventSchemaEnforcementEnabled: config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
                    overflowEnabled: deps.overflowEnabled,
                    preservePartitionLocality: config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    personsPrefetchEnabled: config.PERSONS_PREFETCH_ENABLED,
                    cdpHogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
                    outputs,
                    perEventOptions: buildPerEventOptions(config),
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
