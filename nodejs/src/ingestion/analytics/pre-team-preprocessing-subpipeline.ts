import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { TeamManager } from '~/utils/team-manager'

import { EventHeaders, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import {
    createApplyEventRestrictionsStep,
    createDropExceptionEventsStep,
    createEnrichSurveyPersonPropertiesStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateAiEventTokensStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface PreTeamPreprocessingSubpipelineInput {
    message: Message
}

export interface PreTeamPreprocessingSubpipelineOutput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
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
) {
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
        .pipe(createValidateAiEventTokensStep())
        .pipe(createEnrichSurveyPersonPropertiesStep())
}
