import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import {
    createApplyPersonProcessingRestrictionsStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventSchemaStep,
    createValidateEventUuidStep,
} from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface PostTeamPreprocessingSubpipelineInput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
}

export interface PostTeamPreprocessingSubpipelineConfig {
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    eventSchemaEnforcementEnabled: boolean
}

export function createPostTeamPreprocessingSubpipeline<TInput extends PostTeamPreprocessingSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PostTeamPreprocessingSubpipelineConfig
): PipelineBuilder<TInput, TInput, TContext> {
    const { eventIngestionRestrictionManager, eventSchemaEnforcementManager, eventSchemaEnforcementEnabled } = config

    let pipeline = builder.pipe(createValidateEventMetadataStep()).pipe(createValidateEventPropertiesStep())

    if (eventSchemaEnforcementEnabled) {
        pipeline = pipeline.pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager))
    }

    return pipeline
        .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
        .pipe(createValidateEventUuidStep())
        .pipe(createDropOldEventsStep())
}
