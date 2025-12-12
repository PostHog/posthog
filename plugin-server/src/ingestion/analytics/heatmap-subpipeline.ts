import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, PipelineEvent, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { createEventPipelineRunnerHeatmapStep } from '../event-processing/event-pipeline-runner-heatmap-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface HeatmapSubpipelineInput {
    event: PipelineEvent
    team: Team
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export interface HeatmapSubpipelineConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    kafkaProducer: KafkaProducerWrapper
}

export function createHeatmapSubpipeline<TInput extends HeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: HeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, hogTransformer, personsStore, kafkaProducer } = config

    return builder
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep(options.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE))
        .pipe(
            createEventPipelineRunnerHeatmapStep(
                options,
                kafkaProducer,
                teamManager,
                groupTypeManager,
                hogTransformer,
                personsStore
            )
        )
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createSkipEmitEventStep())
}
