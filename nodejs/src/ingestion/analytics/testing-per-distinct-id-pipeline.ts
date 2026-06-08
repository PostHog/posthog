import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { EventOutput, HeatmapsOutput } from './outputs'
import { TestingAiEventSubpipelineInput, createTestingAiEventSubpipeline } from './testing-ai-event-subpipeline'
import { TestingEventSubpipelineInput, createTestingEventSubpipeline } from './testing-event-subpipeline'

export type TestingPerDistinctIdPipelineInput = TestingEventSubpipelineInput & TestingAiEventSubpipelineInput

export interface TestingPerDistinctIdPipelineConfig {
    // The testing event subpipeline extracts scroll-depth heatmap data inline from
    // regular events (e.g. $pageview), so this pipeline still produces HeatmapsOutput
    // even though the dedicated $$heatmap branch has been removed.
    outputs: IngestionOutputs<EventOutput | HeatmapsOutput | IngestionWarningsOutput>
    groupId: string
}

export interface TestingPerDistinctIdPipelineContext {
    message: Message
    team: Team
}

type EventBranch = 'ai' | 'event'

const EVENT_BRANCH_MAP = new Map<string, EventBranch>([
    ...[...AI_EVENT_TYPES].map((t): [string, EventBranch] => [t, 'ai']),
])

function classifyEvent(input: TestingPerDistinctIdPipelineInput): EventBranch {
    return EVENT_BRANCH_MAP.get(input.event.event) ?? 'event'
}

export function createTestingPerDistinctIdPipeline<TInput extends TestingPerDistinctIdPipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: TestingPerDistinctIdPipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { outputs, groupId } = config

    return builder.retry(
        (e) =>
            e.branching<EventBranch, void>(classifyEvent, (branches) =>
                branches
                    .branch('ai', (b) =>
                        createTestingAiEventSubpipeline(b, {
                            outputs,
                            groupId,
                        })
                    )
                    .branch('event', (b) =>
                        createTestingEventSubpipeline(b, {
                            outputs,
                            groupId,
                        })
                    )
            ),
        { tries: 3, sleepMs: 100 }
    )
}
