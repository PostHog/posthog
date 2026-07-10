import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    IngestionWarningsOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TeamManager } from '~/common/utils/team-manager'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { EmitEventStepOutput } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { TopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

export interface AiEventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export interface AiEventSubpipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | IngestionWarningsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | PersonMergeEventsOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
    topHog: TopHogWrapper
}

/**
 * Abstract factory for the AI event sub-pipeline. The analytics lane composes the AI branch through
 * this contract instead of importing the `ai` lane directly; the concrete `createAiEventSubpipeline`
 * (ai lane) is injected at the composition root (servers). This keeps ai and analytics decoupled.
 */
export type AiEventSubpipelineFactory = <TInput extends AiEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: AiEventSubpipelineConfig
) => PipelineBuilder<TInput, EmitEventStepOutput, TContext, AsyncOutput>
