import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { createValidateEventMetadataStep, createValidateEventPropertiesStep } from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'

export interface TestingPostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
}

export function createTestingPostTeamPreprocessingSubpipeline<
    TInput extends TestingPostTeamPreprocessingSubpipelineInput,
    TContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>) {
    // Compared to post-team-preprocessing-subpipeline.ts:
    // REMOVED: createApplyPersonProcessingRestrictionsStep (applies per-token/distinct_id person processing restrictions)
    // REMOVED: createApplyCookielessProcessingStep (rewrites cookieless distinct IDs for person processing)
    // REMOVED: prefetchPersonsStep (prefetches person data from Postgres into cache)
    // REMOVED: processPersonlessDistinctIdsBatchStep (batch inserts personless distinct IDs)
    // REMOVED: createRateLimitToOverflowStep (overflow rate limiting writes to Redis)
    // REMOVED: createOverflowLaneTTLRefreshStep (overflow TTL refresh writes to Redis)
    // REMOVED: createPrefetchHogFunctionsStep (no hog transformations in this pipeline)
    // REMOVED: createValidateEventSchemaStep (no event schema enforcement in this pipeline)
    return builder
        .sequentially((b) => {
            return b
                .pipe(createValidateEventMetadataStep())
                .pipe(createValidateEventPropertiesStep())
                .pipe(createDropOldEventsStep())
        })
        .gather()
}
