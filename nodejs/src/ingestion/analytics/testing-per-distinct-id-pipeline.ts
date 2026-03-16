import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { TestingAiEventSubpipelineInput, createTestingAiEventSubpipeline } from './testing-ai-event-subpipeline'
import { TestingEventSubpipelineInput, createTestingEventSubpipeline } from './testing-event-subpipeline'
import { TestingHeatmapSubpipelineInput, createTestingHeatmapSubpipeline } from './testing-heatmap-subpipeline'

export type TestingPerDistinctIdPipelineInput = TestingEventSubpipelineInput &
    TestingHeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput &
    TestingAiEventSubpipelineInput

export interface TestingPerDistinctIdPipelineConfig {
    options: {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    outputs: IngestionOutputs<EventOutput>
    kafkaProducer: KafkaProducerWrapper
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
    const { options, outputs, kafkaProducer, groupId } = config

    return builder.retry(
        (e) =>
            e.branching<EventBranch, void>(classifyEvent, (branches) => {
                branches
                    .branch('client_ingestion_warning', (b) => createClientIngestionWarningSubpipeline(b))
                    .branch('heatmap', (b) =>
                        createTestingHeatmapSubpipeline(b, {
                            options,
                            kafkaProducer,
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
                            options,
                            outputs,
                            kafkaProducer,
                            groupId,
                        })
                    )
            }),
        { tries: 3, sleepMs: 100 }
    )
}
