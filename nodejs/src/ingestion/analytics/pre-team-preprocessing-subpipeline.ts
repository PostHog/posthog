import { Message } from 'node-rdkafka'

import { TeamManager } from '~/utils/team-manager'

import { EventHeaders, IncomingEvent, IncomingEventWithTeam, Team } from '../../types'
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
    team: Team
}

export interface PreTeamPreprocessingSubpipelineConfig {
    teamManager: TeamManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
}

export function createPreTeamPreprocessingSubpipeline<TInput extends PreTeamPreprocessingSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PreTeamPreprocessingSubpipelineConfig
): PipelineBuilder<TInput, TInput & PreTeamPreprocessingSubpipelineOutput, TContext> {
    const { teamManager, eventIngestionRestrictionManager, overflowEnabled, overflowTopic, preservePartitionLocality } =
        config

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
        .pipe(createResolveTeamStep(teamManager))
        .pipe(createValidateHistoricalMigrationStep())
}
