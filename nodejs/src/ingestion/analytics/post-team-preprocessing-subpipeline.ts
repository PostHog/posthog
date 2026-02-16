import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { processPersonlessDistinctIdsBatchStep } from '~/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { prefetchPersonsStep } from '../../worker/ingestion/event-pipeline/prefetchPersonsStep'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import {
    createApplyCookielessProcessingStep,
    createApplyPersonProcessingRestrictionsStep,
    createFilterIpPropertiesStep,
    createOverflowLaneTTLRefreshStep,
    createRateLimitToOverflowStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventUuidStep,
} from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createPrefetchHogFunctionsStep } from '../event-processing/prefetch-hog-functions-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'

export interface PostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
}

export interface PostTeamPreprocessingSubpipelineConfig {
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    cookielessManager: Hub['cookielessManager']
    overflowTopic: string
    preservePartitionLocality: boolean
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    personsStore: PersonsStore
    personsPrefetchEnabled: boolean
    hogTransformer: HogTransformerService
    cdpHogWatcherSampleRate: number
}

export function createPostTeamPreprocessingSubpipeline<TInput extends PostTeamPreprocessingSubpipelineInput, TContext>(
    builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>,
    config: PostTeamPreprocessingSubpipelineConfig
) {
    const {
        eventIngestionRestrictionManager,
        cookielessManager,
        overflowTopic,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        personsStore,
        personsPrefetchEnabled,
        hogTransformer,
        cdpHogWatcherSampleRate,
    } = config

    return (
        builder
            // These validation steps are synchronous, so we can process events sequentially.
            .sequentially((b) =>
                b
                    .pipe(createValidateEventMetadataStep())
                    .pipe(createValidateEventPropertiesStep())
                    .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
                    .pipe(createValidateEventUuidStep())
                    .pipe(createFilterIpPropertiesStep())
                    .pipe(createDropOldEventsStep())
            )
            // We want to call cookieless with the whole batch at once.
            // IMPORTANT: Cookieless processing changes distinct IDs (cookieless events
            // are captured with $posthog_cookieless distinct ID and rewritten here).
            // Any steps that depend on the final distinct ID must run after this step.
            .gather()
            .pipeBatch(createApplyCookielessProcessingStep(cookielessManager))
            // Rate limit to overflow must run after cookieless, as it uses the final distinct ID
            .pipeBatch(createRateLimitToOverflowStep(overflowTopic, preservePartitionLocality, overflowRedirectService))
            // Refresh TTLs for overflow lane events (keeps Redis flags alive)
            .pipeBatch(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
            // Prefetch must run after cookieless, as cookieless changes distinct IDs
            .pipeBatch(prefetchPersonsStep(personsStore, personsPrefetchEnabled))
            // Batch insert personless distinct IDs after prefetch (uses prefetch cache)
            .pipeBatch(processPersonlessDistinctIdsBatchStep(personsStore, personsPrefetchEnabled))
            // Prefetch hog functions for all teams in the batch
            .pipeBatch(createPrefetchHogFunctionsStep(hogTransformer, cdpHogWatcherSampleRate))
    )
}
