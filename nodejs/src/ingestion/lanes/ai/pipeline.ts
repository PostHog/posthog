import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { createAllowEventsStep } from '~/ingestion/common/steps/allow-events'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { addTeamToContext } from '~/ingestion/common/subpipelines/helpers'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import {
    createApplyCookielessProcessingStep,
    createApplyEventRestrictionsStep,
    createApplyPersonProcessingRestrictionsStep,
    createOnlyCookielessRateLimitToOverflowStep,
    createOverflowLaneTTLRefreshStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createSkipCookielessRateLimitToOverflowStep,
    createValidateAiEventTokensStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/steps/event-preprocessing'
import { createCreateEventStep } from '~/ingestion/steps/event-processing/create-event-step'
import { createDropOldEventsStep } from '~/ingestion/steps/event-processing/drop-old-events-step'
import { EmitEventStepOutput, createEmitEventStep } from '~/ingestion/steps/event-processing/emit-event-step'
import { createFetchPersonBatchStep } from '~/ingestion/steps/event-processing/fetch-person-batch-step'
import { createFlushHogTransformerStep } from '~/ingestion/steps/event-processing/flush-hog-transformer-step'
import { createHogTransformEventStep } from '~/ingestion/steps/event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '~/ingestion/steps/event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '~/ingestion/steps/event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '~/ingestion/steps/event-processing/prepare-event-step'
import { createReadOnlyProcessGroupsStep } from '~/ingestion/steps/event-processing/readonly-process-groups-step'
import {
    SplitAiEventsStepConfig,
    createSplitAiEventsStep,
} from '~/ingestion/steps/event-processing/split-ai-events-step'
import { createStripPersonUpdatePropertiesStep } from '~/ingestion/steps/event-processing/strip-person-update-properties-step'
import { OverflowRedirectService } from '~/ingestion/utils/overflow-redirect/overflow-redirect-service'
import { EventIngestionRestrictionManager } from '~/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/utils/promise-scheduler'
import { TeamManager } from '~/utils/team-manager'

import { AiEventOutput, EVENTS_OUTPUT, EventOutput } from './outputs'
import { createProcessAiEventStep } from './pipelines/steps/process-ai-event-step'

export interface AiIngestionPipelineConfig {
    outputs: IngestionOutputs<
        EventOutput | AiEventOutput | IngestionWarningsOutput | DlqOutput | OverflowOutput | AppMetricsOutput
    >
    teamManager: TeamManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventFilterManager: EventFilterManager
    cookielessManager: CookielessManager
    promiseScheduler: PromiseScheduler
    hogTransformer: HogTransformer
    // Read-only person/group access — the AI pipeline never writes persons or groups.
    personRepository: PersonReadRepository
    groupTypeManager: ReadOnlyGroupTypeManager
    splitAiEventsConfig: SplitAiEventsStepConfig
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    overflowRedirectService: OverflowRedirectService
    overflowLaneTTLRefreshService: OverflowRedirectService
    concurrentBatches: number
}

interface AiIngestionPipelineInput {
    message: Message
}

interface AiIngestionPipelineContext {
    message: Message
}

/**
 * Standalone AI ingestion pipeline. Mirrors the AI branch of the analytics
 * joined pipeline, but:
 *  - only AI events flow through (everything else is DLQ'd by the allow step),
 *  - person and group data are read-only (fetched, never written), like error
 *    tracking — so there are no person/group batch stores or per-distinct-id
 *    ordering, just a batch person fetch + sequential per-event processing,
 *  - overflow uses the dedicated `'ai'` keyspace (wired at service construction),
 *    so AI overflow can never affect analytics.
 *
 * AI events are still double-written to both the events output and the
 * ai_events output (via the split step), keeping it a drop-in for the analytics
 * AI branch once capture-side routing switches over.
 */
export function createAiIngestionPipeline<
    TInput extends AiIngestionPipelineInput,
    TContext extends AiIngestionPipelineContext,
>(config: AiIngestionPipelineConfig) {
    const {
        outputs,
        teamManager,
        eventIngestionRestrictionManager,
        eventFilterManager,
        cookielessManager,
        promiseScheduler,
        hogTransformer,
        personRepository,
        groupTypeManager,
        splitAiEventsConfig,
        overflowEnabled,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        concurrentBatches,
    } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
        outputs,
        promiseScheduler,
    }

    return newBatchingPipeline<
        TInput,
        EmitEventStepOutput,
        TContext,
        EventFiltersBatchContext,
        TContext,
        OverflowOutput
    >(
        (beforeBatch) => beforeBatch.pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs)),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        // Header-only steps: parse headers, allow only AI events, apply token restrictions.
                        .sequentially((b) =>
                            b
                                .pipe(createParseHeadersStep())
                                .pipe(createAllowEventsStep([...AI_EVENT_TYPES]))
                                .pipe(
                                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                        overflowEnabled,
                                        preservePartitionLocality,
                                    })
                                )
                        )
                        // Rate-limit non-cookieless events to overflow before parsing the body.
                        // Cookieless events pass through and are handled post-cookieless below.
                        .pipeBatch(
                            createSkipCookielessRateLimitToOverflowStep(
                                preservePartitionLocality,
                                overflowRedirectService
                            )
                        )
                        // Body parse, team resolution, and AI token validation.
                        .sequentially((b) =>
                            b
                                .pipe(createParseKafkaMessageStep())
                                .pipe(createResolveTeamStep(teamManager))
                                .pipe(createValidateHistoricalMigrationStep())
                                .pipe(createValidateAiEventTokensStep())
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
                                        // Cookieless processing rewrites distinct_id; person fetch keys on the
                                        // final distinct_id, so it must run after this batch step.
                                        .gather()
                                        .pipeBatch(createApplyCookielessProcessingStep(cookielessManager))
                                        .pipeBatch(
                                            createOnlyCookielessRateLimitToOverflowStep(
                                                preservePartitionLocality,
                                                overflowRedirectService
                                            )
                                        )
                                        .pipeBatch(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
                                        // Read-only batch person fetch (no person writes).
                                        .pipeBatch(createFetchPersonBatchStep(personRepository))
                                        .sequentially((b) =>
                                            b
                                                .pipe(createNormalizeProcessPersonFlagStep())
                                                .pipe(createHogTransformEventStep(hogTransformer))
                                                .pipe(createNormalizeEventStep())
                                                .pipe(createProcessAiEventStep())
                                                // Read-only: drop person-update props so they don't
                                                // leak into person_properties (person is never written).
                                                .pipe(createStripPersonUpdatePropertiesStep())
                                                .pipe(createPrepareEventStep())
                                                // Read-only group-type resolution (no new group types created).
                                                .pipe(createReadOnlyProcessGroupsStep(groupTypeManager))
                                                .pipe(createCreateEventStep(EVENTS_OUTPUT))
                                                // Double-write to events + ai_events outputs.
                                                .pipe(createSplitAiEventsStep(splitAiEventsConfig))
                                                .pipe(createEmitEventStep({ outputs }))
                                                .pipe(createRecordIngestionLagStep())
                                        )
                                )
                                .handleIngestionWarnings(outputs)
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false }),
        (afterBatch) =>
            afterBatch
                .pipe(createFlushEventFiltersBatchAppMetricsStep())
                // Drain hog transformer invocation results once per batch.
                .pipe(createFlushHogTransformerStep(hogTransformer)),
        { concurrentBatches }
    )
}
