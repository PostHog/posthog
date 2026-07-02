import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { createAllowEventsStep } from '~/ingestion/common/steps/allow-events'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
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
    createValidateEventSchemaStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createCreateEventStep } from '~/ingestion/common/steps/event-processing/create-event-step'
import { createDropOldEventsStep } from '~/ingestion/common/steps/event-processing/drop-old-events-step'
import { EmitEventStepOutput, createEmitEventStep } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { createFetchPersonBatchStep } from '~/ingestion/common/steps/event-processing/fetch-person-batch-step'
import { createFlushHogTransformerStep } from '~/ingestion/common/steps/event-processing/flush-hog-transformer-step'
import { createHogTransformEventStep } from '~/ingestion/common/steps/event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '~/ingestion/common/steps/event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '~/ingestion/common/steps/event-processing/normalize-process-person-flag-step'
import { createPrefetchHogFunctionsStep } from '~/ingestion/common/steps/event-processing/prefetch-hog-functions-step'
import { createPrepareEventStep } from '~/ingestion/common/steps/event-processing/prepare-event-step'
import { createReadOnlyProcessGroupsStep } from '~/ingestion/common/steps/event-processing/readonly-process-groups-step'
import { createSplitAiEventsStep } from '~/ingestion/common/steps/event-processing/split-ai-events-step'
import { createStripPersonUpdatePropertiesStep } from '~/ingestion/common/steps/event-processing/strip-person-update-properties-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { AI_EVENT_TYPES } from '~/ingestion/common/subpipelines/ai-event-types'
import { addTeamToContext } from '~/ingestion/common/subpipelines/helpers'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { TopHogWrapper, sum, sumOk, sumResult } from '~/ingestion/framework/extensions/tophog'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { isDropResult } from '~/ingestion/framework/results'

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
    overflowEnabled: boolean
    preservePartitionLocality: boolean
    overflowRedirectService: OverflowRedirectService
    overflowLaneTTLRefreshService: OverflowRedirectService
    concurrentBatches: number
    cdpHogWatcherSampleRate: number
    eventSchemaEnforcementEnabled: boolean
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    topHog: TopHogWrapper
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
        overflowEnabled,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        concurrentBatches,
        cdpHogWatcherSampleRate,
        eventSchemaEnforcementEnabled,
        eventSchemaEnforcementManager,
        topHog,
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
                                        .sequentially((b) => {
                                            const validated = b
                                                .pipe(createValidateEventMetadataStep())
                                                .pipe(createValidateEventPropertiesStep())
                                            // Schema enforcement is opt-in (same as analytics); only
                                            // applied when enabled so AI events match that path.
                                            const schemaChecked = eventSchemaEnforcementEnabled
                                                ? validated.pipe(
                                                      createValidateEventSchemaStep(eventSchemaEnforcementManager)
                                                  )
                                                : validated
                                            return schemaChecked
                                                .pipe(
                                                    createApplyPersonProcessingRestrictionsStep(
                                                        eventIngestionRestrictionManager
                                                    )
                                                )
                                                .pipe(createDropOldEventsStep())
                                                .pipe(createApplyEventFiltersStep(eventFilterManager))
                                        })
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
                                        // Prefetch hog functions for the batch's teams so the transformer
                                        // honors Hog watcher's disabled-function state (mirrors analytics).
                                        .pipeBatch(
                                            createPrefetchHogFunctionsStep(hogTransformer, cdpHogWatcherSampleRate)
                                        )
                                        .sequentially((b) =>
                                            // Retry the per-event chain on transient failures (hog
                                            // transform, group-type fetch, emit), matching the
                                            // analytics per-distinct-id retry.
                                            b.retry(
                                                (e) =>
                                                    e
                                                        .pipe(createNormalizeProcessPersonFlagStep())
                                                        .pipe(
                                                            topHog(createHogTransformEventStep(hogTransformer), [
                                                                sumOk(
                                                                    'transformations_run',
                                                                    (output) => ({ team_id: String(output.team.id) }),
                                                                    (output) => output.transformationsRun
                                                                ),
                                                                sumOk(
                                                                    'transformations_run_per_partition',
                                                                    (output, input) => ({
                                                                        team_id: String(output.team.id),
                                                                        partition: String(input.message.partition),
                                                                    }),
                                                                    (output) => output.transformationsRun
                                                                ),
                                                                sumResult(
                                                                    'events_dropped_by_transformation',
                                                                    (_result, input) => ({
                                                                        team_id: String(input.team.id),
                                                                    }),
                                                                    (result) => (isDropResult(result) ? 1 : 0)
                                                                ),
                                                                sumResult(
                                                                    'events_dropped_by_transformation_per_partition',
                                                                    (_result, input) => ({
                                                                        team_id: String(input.team.id),
                                                                        partition: String(input.message.partition),
                                                                    }),
                                                                    (result) => (isDropResult(result) ? 1 : 0)
                                                                ),
                                                            ])
                                                        )
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
                                                        .pipe(createSplitAiEventsStep())
                                                        .pipe(
                                                            topHog(createEmitEventStep({ outputs }), [
                                                                sum(
                                                                    'emitted_events',
                                                                    (input) => ({ team_id: String(input.teamId) }),
                                                                    (input) => input.eventsToEmit.length
                                                                ),
                                                                sum(
                                                                    'emitted_events_per_partition',
                                                                    (input) => ({
                                                                        team_id: String(input.teamId),
                                                                        partition: String(input.message.partition),
                                                                    }),
                                                                    (input) => input.eventsToEmit.length
                                                                ),
                                                            ])
                                                        )
                                                        .pipe(createRecordIngestionLagStep()),
                                                { tries: 5, sleepMs: 100, name: 'ai_event' }
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
                .pipe(createFlushEventFiltersBatchAppMetricsStep())
                // Drain hog transformer invocation results once per batch.
                .pipe(createFlushHogTransformerStep(hogTransformer)),
        { concurrentBatches }
    )
}
