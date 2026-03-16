import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { AI_EVENT_TYPES } from '../ai'
import { AiEventSubpipelineInput, createAiEventSubpipeline } from '../ai/pipelines/ai-event-subpipeline'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { AiEventOutput, EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '../pipelines/extensions/tophog'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { HeatmapSubpipelineInput, createHeatmapSubpipeline } from './heatmap-subpipeline'

export type PerDistinctIdPipelineInput = EventSubpipelineInput &
    HeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput &
    AiEventSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    outputs: IngestionOutputs<EventOutput | AiEventOutput>
    splitAiEventsConfig: SplitAiEventsStepConfig
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
    topHog: TopHogWrapper
}

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

type EventBranch = 'client_ingestion_warning' | 'heatmap' | 'ai' | 'event'

const EVENT_BRANCH_MAP = new Map<string, EventBranch>([
    ['$$client_ingestion_warning', 'client_ingestion_warning'],
    ['$$heatmap', 'heatmap'],
    ...[...AI_EVENT_TYPES].map((t): [string, EventBranch] => [t, 'ai']),
])

function classifyEvent(input: PerDistinctIdPipelineInput): EventBranch {
    return EVENT_BRANCH_MAP.get(input.event.event) ?? 'event'
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerDistinctIdPipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const {
        options,
        outputs,
        splitAiEventsConfig,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        groupStore,
        kafkaProducer,
        groupId,
        topHog,
    } = config

    return builder.retry(
        (e) =>
            e.branching<EventBranch, void>(classifyEvent, (branches) => {
                branches
                    .branch('client_ingestion_warning', (b) => createClientIngestionWarningSubpipeline(b))
                    .branch('heatmap', (b) =>
                        createHeatmapSubpipeline(b, {
                            options,
                            teamManager,
                            groupTypeManager,
                            groupStore,
                            kafkaProducer,
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
                            kafkaProducer,
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
                            kafkaProducer,
                            groupId,
                            topHog,
                        })
                    )
            }),
        { tries: 3, sleepMs: 100 }
    )
}
