import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import {
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventSchemaStep,
} from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'

export interface TestingPostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
}

export interface TestingPostTeamPreprocessingSubpipelineConfig {
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    eventSchemaEnforcementEnabled: boolean
}

export function createTestingPostTeamPreprocessingSubpipeline<
    TInput extends TestingPostTeamPreprocessingSubpipelineInput,
    TContext,
>(
    builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>,
    config: TestingPostTeamPreprocessingSubpipelineConfig
) {
    const { eventSchemaEnforcementManager, eventSchemaEnforcementEnabled } = config

    // Compared to post-team-preprocessing-subpipeline.ts:
    // REMOVED: createApplyPersonProcessingRestrictionsStep (applies per-token/distinct_id person processing restrictions)
    // REMOVED: createApplyCookielessProcessingStep (rewrites cookieless distinct IDs for person processing)
    // REMOVED: prefetchPersonsStep (prefetches person data from Postgres into cache)
    // REMOVED: processPersonlessDistinctIdsBatchStep (batch inserts personless distinct IDs)
    // REMOVED: createRateLimitToOverflowStep (overflow rate limiting writes to Redis)
    // REMOVED: createOverflowLaneTTLRefreshStep (overflow TTL refresh writes to Redis)
    // REMOVED: createPrefetchHogFunctionsStep (no hog transformations in this pipeline)
    return builder
        .sequentially((b) => {
            const validated = b.pipe(createValidateEventMetadataStep()).pipe(createValidateEventPropertiesStep())

            const schemaChecked = eventSchemaEnforcementEnabled
                ? validated.pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager))
                : validated

            return schemaChecked.pipe(createDropOldEventsStep())
        })
        .gather()
}
