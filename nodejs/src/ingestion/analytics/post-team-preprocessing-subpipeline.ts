import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, IncomingEventWithTeam, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { createExpandOtelRawDataStep } from '../ai/otel-preprocessing'
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
    kafkaProducer: KafkaProducerWrapper
}

export function createPostTeamPreprocessingSubpipeline<TInput extends PostTeamPreprocessingSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PostTeamPreprocessingSubpipelineConfig
): PipelineBuilder<TInput, TInput, TContext> {
    const { eventIngestionRestrictionManager, kafkaProducer } = config

    return builder
        .pipe(createExpandOtelRawDataStep(kafkaProducer))
        .pipe(createValidateEventMetadataStep())
        .pipe(createValidateEventPropertiesStep())
        .pipe(createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager))
        .pipe(createValidateEventUuidStep())
}
