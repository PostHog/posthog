import { Message } from 'node-rdkafka'

import { processPersonlessDistinctIdsBatchStep } from '~/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { prefetchPersonsStep } from '../../worker/ingestion/event-pipeline/prefetchPersonsStep'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { HeatmapsOutput, PersonDistinctIdsOutput, PersonsOutput } from '../analytics/outputs'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '../common/steps/event-filters-steps'
import { addTeamToContext, getTokenAndDistinctId } from '../common/subpipelines/helpers'
import { CookielessManager } from '../cookieless/cookieless-manager'
import {
    createApplyCookielessProcessingStep,
    createApplyEventRestrictionsStep,
    createApplyPersonProcessingRestrictionsStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createFlushBatchStoresStep } from '../event-processing/flush-batch-stores-step'
import { createPrefetchHogFunctionsStep } from '../event-processing/prefetch-hog-functions-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { HeatmapEventOptions, createHeatmapSubpipeline } from './heatmap-subpipeline'

export interface HeatmapsPipelineConfig {
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
    perEventOptions: HeatmapEventOptions
}

export interface HeatmapsPipelineDeps {
    teamManager: TeamManager
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    cookielessManager: CookielessManager
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
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
 * Mirrors the analytics-pipeline shape but inlines a heatmap-specific pre-team
 * and post-team chain to drop steps that don't apply to a heatmap-only topic:
 *   pre-team: no `dropExceptionEvents`, `validateAiEventTokens`,
 *     `enrichSurveyPersonProperties` (heatmap topic doesn't carry those events).
 *   post-team: no schema enforcement (no user schemas for `$$heatmap`),
 *     no rate-limit-to-overflow, no overflow-lane-TTL-refresh
 *     (heatmaps don't redirect to overflow).
 *
 * Persons + groups behavior preserved (matches what the joined pipeline did
 * for heatmap events): `prefetchPersonsStep`, `processPersonlessDistinctIds`,
 * `processGroupsStep` all run.
 */
export function createHeatmapsPipeline<TInput extends HeatmapsPipelineInput, TContext extends HeatmapsPipelineContext>(
    config: HeatmapsPipelineConfig,
    deps: HeatmapsPipelineDeps
) {
    const { preservePartitionLocality, personsPrefetchEnabled, cdpHogWatcherSampleRate, outputs, perEventOptions } =
        config

    const {
        teamManager,
        eventFilterManager,
        eventIngestionRestrictionManager,
        cookielessManager,
        personsStore,
        groupStore,
        groupTypeManager,
        hogTransformer,
        promiseScheduler,
    } = deps

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
        outputs,
        promiseScheduler,
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
                            b
                                .pipe(createParseHeadersStep())
                                .pipe(
                                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                        // Heatmap-only topic — no overflow redirect path.
                                        overflowEnabled: false,
                                        preservePartitionLocality,
                                    })
                                )
                                .pipe(createParseKafkaMessageStep())
                                .pipe(createResolveTeamStep(teamManager))
                                .pipe(createValidateHistoricalMigrationStep())
                        )
                        .filterMap(addTeamToContext, (b) =>
                            b
                                .teamAware((b) =>
                                    b
                                        .sequentially((b) =>
                                            b
                                                .pipe(createValidateEventMetadataStep())
                                                .pipe(createValidateEventPropertiesStep())
                                                .pipe(
                                                    createApplyPersonProcessingRestrictionsStep(
                                                        eventIngestionRestrictionManager
                                                    )
                                                )
                                                .pipe(createDropOldEventsStep())
                                                .pipe(createApplyEventFiltersStep(eventFilterManager))
                                        )
                                        .gather()
                                        .pipeBatch(createApplyCookielessProcessingStep(cookielessManager))
                                        .pipeBatch(prefetchPersonsStep(personsStore, personsPrefetchEnabled))
                                        .pipeBatch(
                                            processPersonlessDistinctIdsBatchStep(personsStore, personsPrefetchEnabled)
                                        )
                                        .pipeBatch(
                                            createPrefetchHogFunctionsStep(hogTransformer, cdpHogWatcherSampleRate)
                                        )
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
