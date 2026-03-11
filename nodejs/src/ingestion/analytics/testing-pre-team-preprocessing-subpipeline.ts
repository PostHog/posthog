import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'
import { TeamManager } from '~/utils/team-manager'

import { EventHeaders, Team } from '../../types'
import {
    createDropExceptionEventsStep,
    createEnrichSurveyPersonPropertiesStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateAiEventTokensStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface TestingPreTeamPreprocessingSubpipelineInput {
    message: Message
}

export interface TestingPreTeamPreprocessingSubpipelineOutput {
    message: Message
    headers: EventHeaders
    event: PluginEvent
    team: Team
}

export interface TestingPreTeamPreprocessingSubpipelineConfig {
    teamManager: TeamManager
}

// Compared to pre-team-preprocessing-subpipeline.ts:
// REMOVED: createApplyEventRestrictionsStep (drop/overflow/skip-persons restrictions — not needed in testing pipeline)
export function createTestingPreTeamPreprocessingSubpipeline<
    TInput extends TestingPreTeamPreprocessingSubpipelineInput,
    TContext,
>(builder: StartPipelineBuilder<TInput, TContext>, config: TestingPreTeamPreprocessingSubpipelineConfig) {
    const { teamManager } = config

    return builder
        .pipe(createParseHeadersStep())
        .pipe(createParseKafkaMessageStep())
        .pipe(createDropExceptionEventsStep())
        .pipe(createResolveTeamStep(teamManager))
        .pipe(createValidateHistoricalMigrationStep())
        .pipe(createValidateAiEventTokensStep())
        .pipe(createEnrichSurveyPersonPropertiesStep())
}
