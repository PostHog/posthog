import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { EventOutput, HeatmapsOutput } from './outputs'
import { TestingAiEventSubpipelineInput, createTestingAiEventSubpipeline } from './testing-ai-event-subpipeline'
import { TestingEventSubpipelineInput, createTestingEventSubpipeline } from './testing-event-subpipeline'
import { TestingHeatmapSubpipelineInput, createTestingHeatmapSubpipeline } from './testing-heatmap-subpipeline'

export type TestingPerDistinctIdPipelineInput = TestingEventSubpipelineInput &
    TestingHeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput &
    TestingAiEventSubpipelineInput

export interface TestingPerDistinctIdPipelineConfig {
    outputs: IngestionOutputs<EventOutput | HeatmapsOutput | IngestionWarningsOutput>
    groupId: string
}

export interface TestingPerDistinctIdPipelineContext {
    message: Message
    team: Team
}

type EventBranch = 'client_ingestion_warning' | 'heatmap' | 'ai' | 'event'

const EVENT_BRANCH_MAP = new Map<string, EventBranch>([
    ['$$client_ingestion_warning', 'client_ingestion_warning'],
    ['$$heatmap', 'heatmap'],
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
                    .branch('client_ingestion_warning', (b) => createClientIngestionWarningSubpipeline(b))
                    .branch('heatmap', (b) =>
                        createTestingHeatmapSubpipeline(b, {
                            outputs,
                        })
                    )
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
