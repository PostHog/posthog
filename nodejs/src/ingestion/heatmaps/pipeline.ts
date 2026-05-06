import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createHeatmapSubpipeline } from '../analytics/heatmap-subpipeline'
import { HeatmapsOutput, PersonDistinctIdsOutput, PersonsOutput } from '../analytics/outputs'
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
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'

export interface HeatmapsPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
    cdpHogWatcherSampleRate: number
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
    perEventOptions: EventPipelineRunnerOptions
}

export interface HeatmapsPipelineDeps {
    teamManager: TeamManager
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    cookielessManager: CookielessManager
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    promiseScheduler: PromiseScheduler
}

export interface HeatmapsPipelineInput {
    message: Message
}

export interface HeatmapsPipelineContext {
    message: Message
}

/**
 * Top-level heatmaps ingestion pipeline.
 *
 * Mirrors the analytics pipeline shape — pre-team preprocessing, post-team
 * preprocessing, group-by `(token, distinct_id)`, concurrently/sequentially —
 * but the per-event step is the heatmap subpipeline rather than the per-distinct-id
 * pipeline. The kafka topic this consumer reads is assumed to carry only
 * `$$heatmap` events; no event-type classification happens here.
 */
export function createHeatmapsPipeline<TInput extends HeatmapsPipelineInput, TContext extends HeatmapsPipelineContext>(
    config: HeatmapsPipelineConfig,
    deps: HeatmapsPipelineDeps
) {
    const {
        eventSchemaEnforcementEnabled,
        overflowEnabled,
        preservePartitionLocality,
        personsPrefetchEnabled,
        cdpHogWatcherSampleRate,
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
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        promiseScheduler,
    } = deps

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
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

    const heatmapSubpipelineConfig = {
        options: perEventOptions,
        outputs,
        teamManager,
        groupTypeManager,
        groupStore,
    }

    return newBatchingPipeline<TInput, void, TContext, EventFiltersBatchContext, TContext, OverflowOutput>(
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
                                                createHeatmapSubpipeline(event, heatmapSubpipelineConfig)
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
