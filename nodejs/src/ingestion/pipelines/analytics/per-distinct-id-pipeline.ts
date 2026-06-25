import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TeamManager } from '~/common/utils/team-manager'
import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'
import { AiEventSubpipelineFactory, AiEventSubpipelineInput } from '~/ingestion/common/ai-subpipeline.contract'
import { EmitEventStepOutput } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { TopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { Team } from '~/types'

import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from './outputs'

export type PerDistinctIdPipelineInput = EventSubpipelineInput & AiEventSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | IngestionWarningsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | PersonMergeEventsOutput
    >
    aiSubpipelineFactory: AiEventSubpipelineFactory
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
    topHog: TopHogWrapper
}

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

type EventBranch = 'ai' | 'event'

const EVENT_BRANCH_MAP = new Map<string, EventBranch>([
    ...[...AI_EVENT_TYPES].map((t): [string, EventBranch] => [t, 'ai']),
])

function classifyEvent(input: PerDistinctIdPipelineInput): EventBranch {
    return EVENT_BRANCH_MAP.get(input.event.event) ?? 'event'
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerDistinctIdPipelineConfig
): PipelineBuilder<TInput, EmitEventStepOutput, TContext, AsyncOutput> {
    const { options, outputs, aiSubpipelineFactory, teamManager, groupTypeManager, hogTransformer, topHog } = config

    return builder.retry(
        (e) =>
            e.branching(classifyEvent, (branches) =>
                branches
                    .branch('ai', (b) =>
                        aiSubpipelineFactory(b, {
                            options,
                            outputs,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            topHog,
                        })
                    )
                    .branch('event', (b) =>
                        createEventSubpipeline(b, {
                            options,
                            outputs,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            topHog,
                        })
                    )
            ),
        { tries: 5, sleepMs: 100, name: 'per_distinct_id' }
    )
}
