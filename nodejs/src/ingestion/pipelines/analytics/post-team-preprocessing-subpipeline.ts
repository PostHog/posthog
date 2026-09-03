import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { EventFiltersBatchAppMetrics } from '~/ingestion/common/event-filters/batch-app-metrics'
import { FeatureFlagCalledDedupService } from '~/ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { createApplyEventFiltersStep } from '~/ingestion/common/steps/event-filters-steps'
import {
    createApplyCookielessProcessingStep,
    createApplyPersonProcessingRestrictionsStep,
    createDedupeFeatureFlagCalledStep,
    createOnlyCookielessRateLimitToOverflowStep,
    createOverflowLaneTTLRefreshStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventSchemaStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createDropOldEventsStep } from '~/ingestion/common/steps/event-processing/drop-old-events-step'
import { ChunkPipelineBuilder } from '~/ingestion/framework/builders/chunk-pipeline-builders'
import { prefetchEventSchemasStep } from '~/ingestion/pipelines/analytics/steps/prefetchEventSchemasStep'
import { prefetchGroupsStep } from '~/ingestion/pipelines/analytics/steps/prefetchGroupsStep'
import { prefetchHogFunctionsStep } from '~/ingestion/pipelines/analytics/steps/prefetchHogFunctionsStep'
import { prefetchPersonsStep } from '~/ingestion/pipelines/analytics/steps/prefetchPersonsStep'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

export interface PostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
    eventFiltersBatchAppMetrics: EventFiltersBatchAppMetrics
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export interface PostTeamPreprocessingSubpipelineConfig {
    eventFilterManager: EventFilterManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    eventSchemaEnforcementEnabled: boolean
    cookielessManager: CookielessManager
    preservePartitionLocality: boolean
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    featureFlagCalledDedupService?: FeatureFlagCalledDedupService
    personsPrefetchEnabled: boolean
    groupsPrefetchEnabled: boolean
    eventSchemasPrefetchEnabled: boolean
    hogFunctionsPrefetchEnabled: boolean
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
}

export function createPostTeamPreprocessingSubpipeline<
    TStart,
    TInput extends PostTeamPreprocessingSubpipelineInput,
    TContext,
    R extends string = never,
    D = unknown,
>(
    builder: ChunkPipelineBuilder<TStart, TInput, TContext, TContext, R, D>,
    config: PostTeamPreprocessingSubpipelineConfig
) {
    const {
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
        eventSchemasPrefetchEnabled,
        hogFunctionsPrefetchEnabled,
        groupTypeManager,
        hogTransformer,
    } = config

    return (
        builder
            // Warm the schema cache with one batched load per chunk before the sequential chain
            // below reads it one event at a time. The prefetch shares the enforcement flag,
            // matching when the validation step reads the cache.
            .pipeChunk(
                prefetchEventSchemasStep(
                    eventSchemaEnforcementManager,
                    eventSchemasPrefetchEnabled && eventSchemaEnforcementEnabled
                )
            )
            // These validation steps are synchronous, so we can process events sequentially.
            .sequentially((b) =>
                b
                    .pipe(createValidateEventMetadataStep())
                    .pipe(createValidateEventPropertiesStep())
                    // Schema enforcement is opt-in; the step passes events through when disabled.
                    .pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager, eventSchemaEnforcementEnabled))
                    .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
                    .pipe(createDropOldEventsStep())
                    .pipe(createApplyEventFiltersStep(eventFilterManager))
            )
            // We want to call cookieless with the whole batch at once.
            // IMPORTANT: Cookieless processing changes distinct IDs (cookieless events
            // are captured with $posthog_cookieless distinct ID and rewritten here).
            // Any steps that depend on the final distinct ID must run after this step.
            .gather()
            .pipeChunk(createApplyCookielessProcessingStep(cookielessManager))
            // Rate-limit only cookieless events using the hashed distinct_id assigned by the
            // cookieless step. Non-cookieless events were rate-limited pre-parse in the joined
            // pipeline via createSkipCookielessRateLimitToOverflowStep.
            .pipeChunk(createOnlyCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
            // Refresh TTLs for overflow lane events (keeps Redis flags alive)
            .pipeChunk(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
            // Drop redundant $feature_flag_called events (keep-first Redis claim).
            // Must run after cookieless (keys on the final distinct_id) and before
            // person prefetch so duplicates skip person processing and the CH write.
            .pipeChunk(createDedupeFeatureFlagCalledStep(featureFlagCalledDedupService))
            // Prefetch must run after cookieless, as cookieless changes distinct IDs.
            // Prefetch is fire-and-forget (best-effort cache warming), so retry here would be a
            // no-op — transient persons-Postgres failures are swallowed inside prefetchPersons so
            // they can't surface as an unhandled rejection and crash the worker.
            .pipeChunk(prefetchPersonsStep(personsPrefetchEnabled))
            // Same best-effort, fire-and-forget cache warming for groups: one
            // batched fetch for the chunk's $groupidentify group keys.
            .pipeChunk(prefetchGroupsStep(groupTypeManager, groupsPrefetchEnabled))
            // Warm the transformation hog-function cache last, after the drop steps above, so
            // only teams with surviving events are loaded. The transformer runs much later in
            // the event subpipeline, so the load still lands well ahead of its reads.
            .pipeChunk(prefetchHogFunctionsStep(hogTransformer, hogFunctionsPrefetchEnabled))
    )
}
