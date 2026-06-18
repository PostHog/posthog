import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    IngestionWarningsOutput,
    PersonDistinctIdsOutput,
    PersonsOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { EventPipelineRunnerOptions } from '~/ingestion/event-processing/event-pipeline-options'
import { SplitAiEventsStepConfig } from '~/ingestion/event-processing/split-ai-events-step'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '~/ingestion/pipelines/extensions/tophog'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'
import { TeamManager } from '~/utils/team-manager'

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
        EventOutput | AiEventOutput | IngestionWarningsOutput | PersonsOutput | PersonDistinctIdsOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
    splitAiEventsConfig: SplitAiEventsStepConfig
    groupId: string
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
) => PipelineBuilder<TInput, void, TContext, AsyncOutput>
