import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import {
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '../common/steps/event-filters-steps'
import { IngestionBatchContext, createPersonsStoreBeforeBatchStep } from '../common/steps/persons-store-batch-step'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createFlushBatchStoresStep } from '../event-processing/flush-batch-stores-step'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { TopHogRegistry, createTopHogWrapper } from '../pipelines/extensions/tophog'
import { OkResultWithContext } from '../pipelines/pipeline.interface'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    HeatmapsOutput,
    PersonDistinctIdsOutput,
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
import { createPreTeamPreprocessingSubpipeline } from './pre-team-preprocessing-subpipeline'

export interface JoinedIngestionPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
    cdpHogWatcherSampleRate: number
    groupId: string
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
    splitAiEventsConfig: SplitAiEventsStepConfig
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
    hogTransformer: HogTransformerService
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    promiseScheduler: PromiseScheduler
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
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
        groupId,
        outputs,
        splitAiEventsConfig,
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
        teamManager,
        cookielessManager,
        groupTypeManager,
        topHog,
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
        personsPrefetchEnabled,
        hogTransformer,
        cdpHogWatcherSampleRate,
    }

    const perEventConfig: PerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        outputs,
        splitAiEventsConfig,
        teamManager,
        groupTypeManager,
        hogTransformer,
        groupStore,
        groupId,
        topHog: topHogWrapper,
    }

    return newBatchingPipeline<TInput, void, TContext, IngestionBatchContext, TContext, OverflowOutput | AsyncOutput>(
        (beforeBatch) =>
            beforeBatch
                .pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs))
                .pipe(createPersonsStoreBeforeBatchStep(personsStore)),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            createPreTeamPreprocessingSubpipeline(b, {
                                teamManager,
                                eventIngestionRestrictionManager,
                                overflowEnabled,
                                preservePartitionLocality,
                            })
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
                .pipe(createFlushEventFiltersBatchAppMetricsStep()),
        // Batch stores (personsStore, groupStore) are singletons that don't support
        // concurrent batches yet — they accumulate state across events and flush once.
        // The Rust consumer's per-worker Semaphore caps in-flight batches at the
        // same value (INGESTION_WORKER_CONCURRENT_BATCHES); divergence shows up as
        // HTTP 503s in `ingestion_api_batch_capacity_rejections_total`.
        { concurrentBatches }
    )
}
