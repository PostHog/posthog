import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { AI_EVENT_TYPES } from '../ai'
import { AiEventSubpipelineInput, createAiEventSubpipeline } from '../ai/pipelines/ai-event-subpipeline'
import { IngestionWarningsOutput } from '../common/outputs'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '../pipelines/extensions/tophog'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { HeatmapSubpipelineInput, createHeatmapSubpipeline } from './heatmap-subpipeline'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    HeatmapsOutput,
    PersonDistinctIdsOutput,
    PersonsOutput,
} from './outputs'

export type PerDistinctIdPipelineInput = EventSubpipelineInput & HeatmapSubpipelineInput & AiEventSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        EventOutput | AiEventOutput | HeatmapsOutput | IngestionWarningsOutput | PersonsOutput | PersonDistinctIdsOutput
    >
    splitAiEventsConfig: SplitAiEventsStepConfig
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

type EventBranch = 'heatmap' | 'ai' | 'event'

const EVENT_BRANCH_MAP = new Map<string, EventBranch>([
    ['$$heatmap', 'heatmap'],
    ...[...AI_EVENT_TYPES].map((t): [string, EventBranch] => [t, 'ai']),
])

function classifyEvent(input: PerDistinctIdPipelineInput): EventBranch {
    return EVENT_BRANCH_MAP.get(input.event.event) ?? 'event'
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerDistinctIdPipelineConfig
): PipelineBuilder<TInput, void, TContext, AsyncOutput> {
    const {
        options,
        outputs,
        splitAiEventsConfig,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        groupStore,
        groupId,
        topHog,
    } = config

    return builder.retry(
        (e) =>
            e.branching(classifyEvent, (branches) =>
                branches
                    .branch('heatmap', (b) =>
                        createHeatmapSubpipeline(b, {
                            options,
                            outputs,
                            teamManager,
                            groupTypeManager,
                            groupStore,
                        })
                    )
                    .branch('ai', (b) =>
                        createAiEventSubpipeline(b, {
                            options,
                            outputs,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            personsStore,
                            groupStore,
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
                            personsStore,
                            groupStore,
                            groupId,
                            topHog,
                        })
                    )
            ),
        { tries: 3, sleepMs: 100 }
    )
}
