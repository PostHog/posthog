import { Message } from 'node-rdkafka'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { EventFiltersBatchAppMetrics } from '~/ingestion/common/event-filters/batch-app-metrics'
import { FeatureFlagCalledDedupService } from '~/ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
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
import { createPrefetchHogFunctionsStep } from '~/ingestion/common/steps/event-processing/prefetch-hog-functions-step'
import { BatchPipelineBuilder } from '~/ingestion/framework/builders/batch-pipeline-builders'
import { prefetchPersonsStep } from '~/ingestion/pipelines/analytics/steps/prefetchPersonsStep'
import { processPersonlessDistinctIdsBatchStep } from '~/ingestion/pipelines/analytics/steps/processPersonlessDistinctIdsBatchStep'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

export interface PostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
    eventFiltersBatchAppMetrics: EventFiltersBatchAppMetrics
    personsStoreForBatch: PersonsStoreForBatch
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
    flagCalledPersonlessDefaultTeams: string
    hogTransformer: HogTransformer
    cdpHogWatcherSampleRate: number
}

export function createPostTeamPreprocessingSubpipeline<TInput extends PostTeamPreprocessingSubpipelineInput, TContext>(
    builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>,
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
        flagCalledPersonlessDefaultTeams,
        hogTransformer,
        cdpHogWatcherSampleRate,
    } = config

    return (
        builder
            // These validation steps are synchronous, so we can process events sequentially.
            .sequentially((b) => {
                const validated = b.pipe(createValidateEventMetadataStep()).pipe(createValidateEventPropertiesStep())

                const schemaChecked = eventSchemaEnforcementEnabled
                    ? validated.pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager))
                    : validated

                return schemaChecked
                    .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
                    .pipe(createDropOldEventsStep())
                    .pipe(createApplyEventFiltersStep(eventFilterManager))
            })
            // We want to call cookieless with the whole batch at once.
            // IMPORTANT: Cookieless processing changes distinct IDs (cookieless events
            // are captured with $posthog_cookieless distinct ID and rewritten here).
            // Any steps that depend on the final distinct ID must run after this step.
            .gather()
            .pipeBatch(createApplyCookielessProcessingStep(cookielessManager))
            // Rate-limit only cookieless events using the hashed distinct_id assigned by the
            // cookieless step. Non-cookieless events were rate-limited pre-parse in the joined
            // pipeline via createSkipCookielessRateLimitToOverflowStep.
            .pipeBatch(createOnlyCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
            // Refresh TTLs for overflow lane events (keeps Redis flags alive)
            .pipeBatch(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
            // Drop redundant $feature_flag_called events (keep-first Redis claim).
            // Must run after cookieless (keys on the final distinct_id) and before
            // person prefetch so duplicates skip person processing and the CH write.
            .pipeBatch(createDedupeFeatureFlagCalledStep(featureFlagCalledDedupService))
            // Prefetch must run after cookieless, as cookieless changes distinct IDs.
            // Prefetch is fire-and-forget (best-effort cache warming), so retry here would be a
            // no-op — transient persons-Postgres failures are swallowed inside prefetchPersons so
            // they can't surface as an unhandled rejection and crash the worker.
            .pipeBatch(prefetchPersonsStep(personsPrefetchEnabled))
            // Batch insert personless distinct IDs after prefetch (uses prefetch cache).
            // This step awaits its DB write, so retry transient persons-Postgres failures
            // (e.g. PgBouncer scale-down) instead of letting them crash the consumer loop.
            .pipeBatchWithRetry(
                processPersonlessDistinctIdsBatchStep(personsPrefetchEnabled, flagCalledPersonlessDefaultTeams),
                {
                    tries: 5,
                    sleepMs: 100,
                    name: 'personless_distinct_ids',
                }
            )
            // Prefetch hog functions for all teams in the batch
            .pipeBatch(createPrefetchHogFunctionsStep(hogTransformer, cdpHogWatcherSampleRate))
    )
}
