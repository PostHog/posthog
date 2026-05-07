import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { AiEventOutput, AsyncOutput, EventOutput, PersonDistinctIdsOutput, PersonsOutput } from '../analytics/outputs'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import {
    EventFiltersBatchContext,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '../common/steps/event-filters-steps'
import { addTeamToContext, getTokenAndDistinctId } from '../common/subpipelines/helpers'
import {
    PostTeamPreprocessingSubpipelineConfig,
    createPostTeamPreprocessingSubpipeline,
} from '../common/subpipelines/post-team-preprocessing'
import { createPreTeamPreprocessingSubpipeline } from '../common/subpipelines/pre-team-preprocessing'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createFlushBatchStoresStep } from '../event-processing/flush-batch-stores-step'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { TopHogRegistry, createTopHogWrapper } from '../pipelines/extensions/tophog'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { createAiEventSubpipeline } from './pipelines/ai-event-subpipeline'

export interface AiPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
    cdpHogWatcherSampleRate: number
    groupId: string
    splitAiEventsConfig: SplitAiEventsStepConfig
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
        | AppMetricsOutput
    >
    perEventOptions: EventPipelineRunnerOptions
}

export interface AiPipelineDeps {
    teamManager: TeamManager
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    cookielessManager: CookielessManager
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    topHog: TopHogRegistry
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    promiseScheduler: PromiseScheduler
}

export interface AiPipelineInput {
    message: Message
}

export interface AiPipelineContext {
    message: Message
}

/**
 * Top-level AI ingestion pipeline.
 *
 * Mirrors the analytics pipeline shape — pre-team preprocessing, post-team
 * preprocessing, group-by `(token, distinct_id)`, concurrently/sequentially —
 * but the per-event step is the AI event subpipeline. Assumes the kafka topic
 * this consumer reads only carries AI events; no event-type classification
 * happens here.
 */
export function createAiPipeline<TInput extends AiPipelineInput, TContext extends AiPipelineContext>(
    config: AiPipelineConfig,
    deps: AiPipelineDeps
) {
    const {
        eventSchemaEnforcementEnabled,
        overflowEnabled,
        preservePartitionLocality,
        personsPrefetchEnabled,
        cdpHogWatcherSampleRate,
        groupId,
        splitAiEventsConfig,
        outputs,
        perEventOptions,
    } = config

    const {
        teamManager,
        eventFilterManager,
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        cookielessManager,
        personsStore,
        groupStore,
        groupTypeManager,
        hogTransformer,
        topHog,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        promiseScheduler,
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
        personsStore,
        personsPrefetchEnabled,
        hogTransformer,
        cdpHogWatcherSampleRate,
    }

    const aiEventConfig = {
        options: perEventOptions,
        outputs,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        groupStore,
        splitAiEventsConfig,
        groupId,
        topHog: topHogWrapper,
    }

    return newBatchingPipeline<
        TInput,
        void,
        TContext,
        EventFiltersBatchContext,
        TContext,
        OverflowOutput | AsyncOutput
    >(
        (beforeBatch) => beforeBatch.pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs)),
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
                                        .groupBy(getTokenAndDistinctId)
                                        .concurrently((eventsForDistinctId) =>
                                            eventsForDistinctId.sequentially((event) =>
                                                createAiEventSubpipeline(event, aiEventConfig)
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
        { concurrentBatches: 1 }
    )
}
