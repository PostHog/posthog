import { EventHeaders, IncomingEventWithTeam, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import {
    createApplyPersonProcessingRestrictionsStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateEventUuidStep,
} from '../event-preprocessing'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface PostTeamPreprocessingSubpipelineInput {
    headers: EventHeaders
    eventWithTeam: IncomingEventWithTeam
    team: Team
}

export interface PostTeamPreprocessingSubpipelineConfig {
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
}

export function createPostTeamPreprocessingSubpipeline<TInput extends PostTeamPreprocessingSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PostTeamPreprocessingSubpipelineConfig
): PipelineBuilder<TInput, TInput, TContext> {
    const { eventIngestionRestrictionManager } = config

    return builder
        .pipe(createValidateEventMetadataStep())
        .pipe(createValidateEventPropertiesStep())
        .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
        .pipe(createValidateEventUuidStep())
}
