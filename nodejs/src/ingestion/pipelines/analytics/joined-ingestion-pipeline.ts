import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { AiEventSubpipelineFactory } from '~/ingestion/common/ai-subpipeline.contract'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { PersonsStore } from '~/ingestion/common/persons/persons-store'
import { createDenyEventsStep } from '~/ingestion/common/steps/deny-events'
import {
    EventFiltersBatchContext,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
import {
    createApplyEventRestrictionsStep,
    createEnrichSurveyPersonPropertiesStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createSkipCookielessRateLimitToOverflowStep,
    createValidateAiEventTokensStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { EmitEventStepOutput } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import { createFlushBatchStoresStep } from '~/ingestion/common/steps/event-processing/flush-batch-stores-step'
import { createFlushHogTransformerStep } from '~/ingestion/common/steps/event-processing/flush-hog-transformer-step'
import {
    GroupStoreBatchContext,
    createGroupStoreBeforeBatchStep,
} from '~/ingestion/common/steps/group-store-batch-step'
import {
    PersonsStoreBatchContext,
    createPersonsStoreBeforeBatchStep,
} from '~/ingestion/common/steps/persons-store-batch-step'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { TopHogRegistry, createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { OkResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { FeatureFlagCalledDedupService } from '~/ingestion/utils/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { OverflowRedirectService } from '~/ingestion/utils/overflow-redirect/overflow-redirect-service'
import { Team } from '~/types'

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
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
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

type IngestionBatchContext = EventFiltersBatchContext & PersonsStoreBatchContext & GroupStoreBatchContext

export interface JoinedIngestionPipelineInput {
    message: Message
}

export interface JoinedIngestionPipelineContext {
    message: Message
}

function addTeamToContext<T extends { team: Team }, C>(
    element: OkResultWithContext<T, C>
): OkResultWithContext<T, C & { team: Team }> {
    return {
        result: element.result,
        context: {
            ...element.context,
            team: element.result.value.team,
        },
    }
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
        overflowEnabled,
        preservePartitionLocality,
        personsPrefetchEnabled,
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

    const pipelineConfig: PipelineConfig<OverflowOutput | AsyncOutput> = {
        outputs,
        promiseScheduler,
    }

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

    return newBatchingPipeline<
        TInput,
        EmitEventStepOutput,
        TContext,
        IngestionBatchContext,
        TContext,
        OverflowOutput | AsyncOutput
    >(
        (beforeBatch) =>
            beforeBatch
                .pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs))
                .pipe(createPersonsStoreBeforeBatchStep(personsStore))
                .pipe(createGroupStoreBeforeBatchStep(groupStore)),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        // Header-only steps: parse Kafka headers and apply token-level restrictions.
                        // Cheap; runs per-event before we touch the body.
                        .sequentially((b) =>
                            b
                                .pipe(createParseHeadersStep())
                                .pipe(createDenyEventsStep(['$exception', '$$client_ingestion_warning', '$$heatmap']))
                                .pipe(
                                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                        overflowEnabled,
                                        preservePartitionLocality,
                                    })
                                )
                        )
                        // Rate-limit non-cookieless events to overflow before parsing the body.
                        // Cookieless events (headers.distinct_id === sentinel) pass through and are
                        // handled by the matching only-cookieless step in post-team, which keys on
                        // the hashed distinct_id assigned by the cookieless step.
                        .pipeBatch(
                            createSkipCookielessRateLimitToOverflowStep(
                                preservePartitionLocality,
                                overflowRedirectService
                            )
                        )
                        // Body parse and team resolution. Anything that needs the parsed event lives here.
                        .sequentially((b) =>
                            b
                                .pipe(createParseKafkaMessageStep())
                                .pipe(createResolveTeamStep(teamManager))
                                .pipe(createValidateHistoricalMigrationStep())
                                .pipe(createValidateAiEventTokensStep())
                                .pipe(createEnrichSurveyPersonPropertiesStep())
                        )
                        .filterMap(addTeamToContext, (b) =>
                            b
                                .teamAware((b) =>
                                    createPostTeamPreprocessingSubpipeline(b, postTeamConfig)
                                        // Group by token:distinctId and process each group concurrently
                                        // Events within each group are processed sequentially
                                        .groupBy(getTokenAndDistinctId)
                                        .concurrently((eventsForDistinctId) =>
                                            eventsForDistinctId.sequentially((event) =>
                                                createPerDistinctIdPipeline(event, perEventConfig)
                                            )
                                        )
                                )
                                .handleIngestionWarnings(outputs)
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false }),
        (afterBatch) =>
            afterBatch
                .pipe(createFlushBatchStoresStep({ personsStore, groupStore, outputs }))
                .pipe(createFlushEventFiltersBatchAppMetricsStep())
                .pipe(createFlushHogTransformerStep(hogTransformer)),
        // Batch stores are singleton persistent caches, but each batch receives a
        // batch-bound view so entries can be reference-counted and released after
        // that batch's flush lifecycle completes. The Rust consumer's per-worker
        // Semaphore caps in-flight batches at the same value
        // (INGESTION_WORKER_CONCURRENT_BATCHES); divergence shows up as HTTP 503s
        // in `ingestion_api_batch_capacity_rejections_total`.
        { concurrentBatches }
    )
}
