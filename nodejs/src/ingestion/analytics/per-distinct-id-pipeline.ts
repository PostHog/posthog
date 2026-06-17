import { Message } from 'node-rdkafka'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { AI_EVENT_TYPES } from '../ai'
import { AiEventSubpipelineInput, createAiEventSubpipeline } from '../ai/pipelines/ai-event-subpipeline'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '../pipelines/extensions/tophog'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { AiEventOutput, AsyncOutput, EventOutput, PersonDistinctIdsOutput, PersonsOutput } from './outputs'

export type PerDistinctIdPipelineInput = EventSubpipelineInput & AiEventSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        EventOutput | AiEventOutput | IngestionWarningsOutput | PersonsOutput | PersonDistinctIdsOutput
    >
    splitAiEventsConfig: SplitAiEventsStepConfig
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
    groupId: string
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
): PipelineBuilder<TInput, void, TContext, AsyncOutput> {
    const { options, outputs, splitAiEventsConfig, teamManager, groupTypeManager, hogTransformer, groupId, topHog } =
        config

    return builder.retry(
        (e) =>
            e.branching(classifyEvent, (branches) =>
                branches
                    .branch('ai', (b) =>
                        createAiEventSubpipeline(b, {
                            options,
                            outputs,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            splitAiEventsConfig,
                            groupId,
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
                            groupId,
                            topHog,
                        })
                    )
            ),
        { tries: 5, sleepMs: 100, name: 'per_distinct_id' }
    )
}
