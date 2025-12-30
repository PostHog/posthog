import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { HeatmapSubpipelineInput, createHeatmapSubpipeline } from './heatmap-subpipeline'

export type PerEventProcessingInput = EventSubpipelineInput &
    HeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput

export interface PerEventProcessingConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
}

type EventBranch = 'client_ingestion_warning' | 'heatmap' | 'event'

function classifyEvent(input: PerEventProcessingInput): EventBranch {
    switch (input.event.event) {
        case '$$client_ingestion_warning':
            return 'client_ingestion_warning'
        case '$$heatmap':
            return 'heatmap'
        default:
            return 'event'
    }
}

export function createPerEventProcessingSubpipeline<TInput extends PerEventProcessingInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerEventProcessingConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, hogTransformer, personsStore, kafkaProducer, groupId } = config

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
                            hogTransformer,
                            personsStore,
                            kafkaProducer,
                        })
                    )
                    .branch('event', (b) =>
                        createEventSubpipeline(b, {
                            options,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            personsStore,
                            kafkaProducer,
                            groupId,
                        })
                    )
            }),
        { tries: 3, sleepMs: 100 }
    )
}
