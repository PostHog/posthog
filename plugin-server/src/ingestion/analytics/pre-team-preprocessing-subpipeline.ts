import { Message } from 'node-rdkafka'

import { EventHeaders, Hub, IncomingEvent, IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import {
    createApplyEventRestrictionsStep,
    createDropExceptionEventsStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface PreTeamPreprocessingSubpipelineInput {
    message: Message
}

export interface PreTeamPreprocessingSubpipelineOutput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
    eventWithTeam: IncomingEventWithTeam
}

export interface PreTeamPreprocessingSubpipelineConfig {
    hub: Hub
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
}

export function createPreTeamPreprocessingSubpipeline<TInput extends PreTeamPreprocessingSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PreTeamPreprocessingSubpipelineConfig
): PipelineBuilder<TInput, TInput & PreTeamPreprocessingSubpipelineOutput, TContext> {
    const { hub, eventIngestionRestrictionManager, overflowEnabled, overflowTopic, preservePartitionLocality } = config

    return builder
        .pipe(createParseHeadersStep())
        .pipe(
            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                overflowEnabled,
                overflowTopic,
                preservePartitionLocality,
            })
        )
        .pipe(createParseKafkaMessageStep())
        .pipe(createDropExceptionEventsStep())
        .pipe(createResolveTeamStep(hub))
        .pipe(createValidateHistoricalMigrationStep())
}
