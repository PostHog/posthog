import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { AI_EVENT_TYPES } from '../ai'
import { AiEventSubpipelineInput, createAiEventSubpipeline } from '../ai/pipelines/ai-event-subpipeline'
import { IngestionWarningsOutput } from '../common/outputs'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
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
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
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
    const { options, outputs, teamManager, groupTypeManager, hogTransformer, groupId, topHog } = config

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
