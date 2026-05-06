import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { IngestionWarningsOutput } from '../common/outputs'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '../pipelines/extensions/tophog'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { AsyncOutput, EventOutput, HeatmapsOutput, PersonDistinctIdsOutput, PersonsOutput } from './outputs'

export type PerDistinctIdPipelineInput = EventSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        EventOutput | HeatmapsOutput | IngestionWarningsOutput | PersonsOutput | PersonDistinctIdsOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    groupId: string
    topHog: TopHogWrapper
}

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerDistinctIdPipelineConfig
): PipelineBuilder<TInput, void, TContext, AsyncOutput> {
    return builder.retry((b) => createEventSubpipeline(b, config), { tries: 3, sleepMs: 100 })
}
