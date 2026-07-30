import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { newCommonIngestionPipeline } from '~/ingestion/common/common-ingestion-pipeline'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { FeatureFlagCalledDedupService } from '~/ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PersonsStore } from '~/ingestion/common/persons/persons-store'
import { createDenyEventsStep } from '~/ingestion/common/steps/deny-events'
import {
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
import {
    createApplyEventRestrictionsStep,
    createEnrichSurveyPersonPropertiesStep,
    createSkipCookielessRateLimitToOverflowStep,
    createValidateAiEventTokensStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import { createFlushBatchStoresStep } from '~/ingestion/common/steps/event-processing/flush-batch-stores-step'
import { createFlushHogTransformerStep } from '~/ingestion/common/steps/event-processing/flush-hog-transformer-step'
import { createGroupStoreBeforeBatchStep } from '~/ingestion/common/steps/group-store-batch-step'
import { createPersonsStoreBeforeBatchStep } from '~/ingestion/common/steps/persons-store-batch-step'
import { AiEventSubpipelineFactory } from '~/ingestion/common/subpipelines/ai-subpipeline.contract'
import { IngestionOverflowMode } from '~/ingestion/config'
import { TopHogRegistry, createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'

import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from './outputs'
import {
    PerDistinctIdPipelineConfig,
    PerDistinctIdPipelineInput,
    createPerDistinctIdPipeline,
} from './per-distinct-id-pipeline'
import {
    PostTeamPreprocessingSubpipelineConfig,
    createPostTeamPreprocessingSubpipeline,
} from './post-team-preprocessing-subpipeline'

export interface JoinedIngestionPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
    groupsPrefetchEnabled: boolean
    cdpHogWatcherSampleRate: number
    outputs: IngestionOutputs<
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
    >
    perDistinctIdOptions: EventPipelineRunnerOptions
    /**
     * Maximum number of batches the BatchingPipeline will accept concurrently.
     * Sourced from `INGESTION_WORKER_CONCURRENT_BATCHES` and MUST match the
     * Rust consumer's per-worker `Semaphore` capacity — divergence causes
     * either idle capacity (consumer under-limits) or HTTP 503s
     * (`ingestion_api_batch_capacity_rejections_total`).
     */
    concurrentBatches: number
}

export interface JoinedIngestionPipelineDeps {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    hogTransformer: HogTransformer
    aiSubpipelineFactory: AiEventSubpipelineFactory
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    promiseScheduler: PromiseScheduler
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    featureFlagCalledDedupService?: FeatureFlagCalledDedupService
    teamManager: TeamManager
    cookielessManager: CookielessManager
    groupTypeManager: GroupTypeManager
    topHog: TopHogRegistry
}

export interface JoinedIngestionPipelineInput {
    message: Message
}

export interface JoinedIngestionPipelineContext {
    message: Message
}

function getTokenAndDistinctId(input: PerDistinctIdPipelineInput): string {
    const token = input.headers.token ?? ''
    const distinctId = input.event.distinct_id ?? ''
    return `${token}:${distinctId}`
}

export function createJoinedIngestionPipeline<
    TInput extends JoinedIngestionPipelineInput,
    TContext extends JoinedIngestionPipelineContext,
>(config: JoinedIngestionPipelineConfig, deps: JoinedIngestionPipelineDeps) {
    const {
        eventSchemaEnforcementEnabled,
        overflowMode,
        preservePartitionLocality,
        personsPrefetchEnabled,
        groupsPrefetchEnabled,
        cdpHogWatcherSampleRate,
        outputs,
        perDistinctIdOptions,
        concurrentBatches,
    } = config

    const {
        personsStore,
        groupStore,
        hogTransformer,
        eventFilterManager,
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        promiseScheduler,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        featureFlagCalledDedupService,
        teamManager,
        cookielessManager,
        groupTypeManager,
        topHog,
        aiSubpipelineFactory,
    } = deps

    const topHogWrapper = createTopHogWrapper(topHog)

    const postTeamConfig: PostTeamPreprocessingSubpipelineConfig = {
        eventFilterManager,
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        eventSchemaEnforcementEnabled,
        cookielessManager,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        featureFlagCalledDedupService,
        personsPrefetchEnabled,
        groupsPrefetchEnabled,
        groupTypeManager,
        flagCalledPersonlessDefaultTeams: perDistinctIdOptions.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
        hogTransformer,
        cdpHogWatcherSampleRate,
    }

    const perEventConfig: PerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        outputs,
        aiSubpipelineFactory,
        teamManager,
        groupTypeManager,
        hogTransformer,
        topHog: topHogWrapper,
    }

    return (
        newCommonIngestionPipeline<TInput, TContext, OverflowOutput | AsyncOutput>({
            teamManager,
            outputs,
            promiseScheduler,
            // Batch stores are singleton persistent caches, but each batch receives a
            // batch-bound view so entries can be reference-counted and released after
            // that batch's flush lifecycle completes. The Rust consumer's per-worker
            // Semaphore caps in-flight batches at the same value
            // (INGESTION_WORKER_CONCURRENT_BATCHES); divergence shows up as HTTP 503s
            // in `ingestion_api_batch_capacity_rejections_total`.
            concurrentBatches,
        })
            .beforeBatch((beforeBatch) =>
                beforeBatch
                    .pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs))
                    .pipe(createPersonsStoreBeforeBatchStep(personsStore))
                    .pipe(createGroupStoreBeforeBatchStep(groupStore))
            )
            // Header-only steps: token-level deny list and restrictions. Cheap; runs
            // per-event before we touch the body.
            .parseHeaders()
            .pipe(createDenyEventsStep(['$exception', '$$client_ingestion_warning', '$$heatmap']))
            .pipe(
                createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                    overflowMode,
                    preservePartitionLocality,
                })
            )
            // Rate-limit non-cookieless events to overflow before parsing the body.
            // Cookieless events (headers.distinct_id === sentinel) pass through and are
            // handled by the matching only-cookieless step in post-team, which keys on
            // the hashed distinct_id assigned by the cookieless step.
            .pipeChunk(createSkipCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
            .parseMessage()
            .resolveTeam()
            .pipe(createValidateHistoricalMigrationStep())
            .pipe(createValidateAiEventTokensStep())
            .pipe(createEnrichSurveyPersonPropertiesStep())
            .compose((b) => createPostTeamPreprocessingSubpipeline(b, postTeamConfig))
            // Group by token:distinctId and process each group concurrently.
            // Events within each group are processed sequentially.
            .concurrentlyPerGroup(getTokenAndDistinctId, (group) =>
                group.sequentially((event) => createPerDistinctIdPipeline(event, perEventConfig))
            )
            .afterBatch((afterBatch) =>
                afterBatch
                    .pipe(createFlushBatchStoresStep({ personsStore, groupStore, outputs }))
                    .pipe(createFlushEventFiltersBatchAppMetricsStep())
                    .pipe(createFlushHogTransformerStep(hogTransformer))
            )
            .build()
    )
}
