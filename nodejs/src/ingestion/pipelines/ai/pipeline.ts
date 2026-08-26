import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'
import { newCommonIngestionPipeline } from '~/ingestion/common/common-ingestion-pipeline'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { createAllowEventsStep } from '~/ingestion/common/steps/allow-events'
import {
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
    createSkipCookielessRateLimitToOverflowStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventSchemaStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createCreateEventStep } from '~/ingestion/common/steps/event-processing/create-event-step'
import { createDropOldEventsStep } from '~/ingestion/common/steps/event-processing/drop-old-events-step'
import { createEmitEventStep } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { createFetchPersonChunkStep } from '~/ingestion/common/steps/event-processing/fetch-person-chunk-step'
import { createFlushHogTransformerStep } from '~/ingestion/common/steps/event-processing/flush-hog-transformer-step'
import { createHogTransformEventStep } from '~/ingestion/common/steps/event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '~/ingestion/common/steps/event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '~/ingestion/common/steps/event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '~/ingestion/common/steps/event-processing/prepare-event-step'
import { createReadOnlyProcessGroupsStep } from '~/ingestion/common/steps/event-processing/readonly-process-groups-step'
import { createStripPersonUpdatePropertiesStep } from '~/ingestion/common/steps/event-processing/strip-person-update-properties-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import {
    createEventUsageBeforeBatchStep,
    createFlushEventUsageStep,
    createRecordEventUsageAfterIngestStep,
    createRecordEventUsageStep,
} from '~/ingestion/common/steps/usage-records-steps'
import { resolveAiUsageKey } from '~/ingestion/common/usage-records/billable-events'
import { IngestionOverflowMode } from '~/ingestion/config'
import { TopHogRegistry, sum, sumOk, sumResult } from '~/ingestion/framework/extensions/tophog'
import { isDropResult } from '~/ingestion/framework/results'

import { BlobStore } from './blob-offload/blob-store'
import { AiEventOutput, EVENTS_OUTPUT, EventOutput } from './outputs'
import {
    OffloadAiBlobsConfig,
    createExtractAiBlobsStep,
    createUploadAiBlobStep,
    extractAiBlobsFanOut,
    mergeAiBlobPointersFanIn,
} from './steps/offload-ai-blobs-step'
import { createProcessAiEventStep } from './steps/process-ai-event-step'
import { createSplitAiEventsStep } from './steps/split-ai-events-step'
import { createValidateAiEventTokensStep } from './steps/validate-ai-event-tokens'

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
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
    overflowRedirectService: OverflowRedirectService
    overflowLaneTTLRefreshService: OverflowRedirectService
    concurrentBatches: number
    eventSchemaEnforcementEnabled: boolean
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    topHog: TopHogRegistry
    aiBlobStore: BlobStore | null
    aiBlobOffloadConfig: OffloadAiBlobsConfig
    createEventUsageBatch?: () => UsageRecordBatch
}

interface AiIngestionPipelineInput {
    message: Message
}

interface AiIngestionPipelineContext {
    message: Message
}

/**
 * Standalone AI ingestion pipeline. Compared to the analytics pipeline:
 *  - only AI events flow through (everything else is DLQ'd by the allow step),
 *  - person and group data are read-only (fetched, never written), like error
 *    tracking — so there are no person/group batch stores or per-distinct-id
 *    ordering, just a batch person fetch + sequential per-event processing,
 *  - overflow uses the dedicated `'ai'` keyspace (wired at service construction),
 *    so AI overflow can never affect analytics.
 *
 * AI events are double-written to both the events output and the ai_events
 * output (via the split step), so they appear on the shared events table as
 * well as the dedicated ai_events table.
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
        overflowMode,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        concurrentBatches,
        eventSchemaEnforcementEnabled,
        eventSchemaEnforcementManager,
        topHog,
        aiBlobStore,
        aiBlobOffloadConfig,
        createEventUsageBatch = () => new UsageRecordBatch(null, { unit: 'events', isTeamEnabled: () => false }),
    } = config

    return (
        newCommonIngestionPipeline<TInput, TContext, OverflowOutput>({
            teamManager,
            outputs,
            promiseScheduler,
            concurrentBatches,
            topHog,
        })
            .beforeBatch((b) =>
                b
                    .pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs))
                    .pipe(createEventUsageBeforeBatchStep(createEventUsageBatch))
            )
            // Header-only steps: allow only AI events, apply token restrictions.
            .parseHeaders()
            .pipe(createAllowEventsStep([...AI_EVENT_TYPES]))
            .pipe(
                createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                    overflowMode,
                    preservePartitionLocality,
                    // createFetchPersonChunkStep below only reads persons.
                    pipelineWritesPersons: false,
                })
            )
            // Rate-limit non-cookieless events to overflow before parsing the body.
            // Cookieless events pass through and are handled post-cookieless below.
            .pipeChunk(createSkipCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
            .parseMessage()
            .resolveTeam()
            .pipe(createValidateHistoricalMigrationStep())
            .pipe(createValidateAiEventTokensStep())
            .pipe(createValidateEventMetadataStep())
            .pipe(createValidateEventPropertiesStep())
            // Schema enforcement is opt-in (same as analytics); the step passes
            // events through when disabled.
            .pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager, eventSchemaEnforcementEnabled))
            .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
            .pipe(createDropOldEventsStep())
            .pipe(createApplyEventFiltersStep(eventFilterManager))
            // Cookieless processing rewrites distinct_id; person fetch keys on the
            // final distinct_id, so it must run after this batch step.
            .gather()
            .pipeChunk(createApplyCookielessProcessingStep(cookielessManager))
            .pipeChunk(createOnlyCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
            .pipeChunk(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
            // Read-only batch person fetch (no person writes). The personhog
            // client retries transient gRPC errors for ~150ms; this outer
            // retry absorbs longer blips that would otherwise crash the
            // worker via an unhandled rejection.
            .pipeChunk(createFetchPersonChunkStep(personRepository), {
                retry: { tries: 5, sleepMs: 100, name: 'fetch_person_chunk' },
            })
            // Per-event chain. Retry is applied per step: only the steps
            // that do transient-failure-prone I/O (hog transform, group-type
            // fetch, emit) retry, matching the analytics per-distinct-id path.
            .pipe(createNormalizeProcessPersonFlagStep())
            .pipe(createHogTransformEventStep(hogTransformer), {
                retry: { tries: 5, sleepMs: 100, name: 'hog_transform_event' },
                topHog: [
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
                ],
            })
            .pipe(createNormalizeEventStep())
            .pipe(createProcessAiEventStep())
            // Blob offload: extract blobs sequentially (cheap, no I/O), then
            // upload them through a fan-out/fan-in stage so per-blob uploads
            // share one concurrency cap across the whole chunk and reuse the
            // pipeline's retry machinery instead of hand-rolled concurrency.
            .pipe(createExtractAiBlobsStep(aiBlobStore, aiBlobOffloadConfig))
            .fanOut(extractAiBlobsFanOut)
            .via((sub) =>
                sub.concurrently(
                    (blob) =>
                        blob.pipe(createUploadAiBlobStep(aiBlobStore), {
                            retry: { tries: 5, sleepMs: 100, name: 'offload_ai_blobs' },
                        }),
                    { maxConcurrency: aiBlobOffloadConfig.uploadMaxConcurrency }
                )
            )
            .fanIn(mergeAiBlobPointersFanIn)
            // Read-only: drop person-update props so they don't
            // leak into person_properties (person is never written).
            .pipe(createStripPersonUpdatePropertiesStep())
            .pipe(createPrepareEventStep())
            // Read-only group-type resolution (no new group types created).
            .pipe(createReadOnlyProcessGroupsStep(groupTypeManager), {
                retry: { tries: 5, sleepMs: 100, name: 'readonly_process_groups' },
            })
            .pipe(createRecordEventUsageStep(resolveAiUsageKey))
            .pipe(createCreateEventStep(EVENTS_OUTPUT))
            // Double-write to events + ai_events outputs.
            .pipe(createSplitAiEventsStep())
            .pipe(createEmitEventStep({ outputs }), {
                retry: { tries: 5, sleepMs: 100, name: 'emit_event' },
                topHog: [
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
                ],
            })
            .pipe(createRecordEventUsageAfterIngestStep())
            .pipe(createRecordIngestionLagStep())
            .afterBatch((b) =>
                b
                    .pipe(createFlushEventFiltersBatchAppMetricsStep())
                    .pipe(createFlushEventUsageStep())
                    // Drain hog transformer invocation results once per batch.
                    .pipe(createFlushHogTransformerStep(hogTransformer))
            )
            .build()
    )
}
