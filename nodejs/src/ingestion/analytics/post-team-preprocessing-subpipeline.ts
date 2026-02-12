import { EventHeaders, IncomingEventWithTeam, Team } from '../../types'
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
    headers: EventHeaders
    eventWithTeam: IncomingEventWithTeam
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

    const validated = builder.pipe(createValidateEventMetadataStep()).pipe(createValidateEventPropertiesStep())

    const schemaChecked = eventSchemaEnforcementEnabled
        ? validated.pipe(createValidateEventSchemaStep(eventSchemaEnforcementManager))
        : validated

    return schemaChecked
        .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
        .pipe(createValidateEventUuidStep())
        .pipe(createDropOldEventsStep())
}
