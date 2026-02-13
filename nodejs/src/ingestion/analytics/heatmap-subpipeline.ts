import { PluginEvent } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { createEventPipelineRunnerHeatmapStep } from '../event-processing/event-pipeline-runner-heatmap-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface HeatmapSubpipelineInput {
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface HeatmapSubpipelineConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

export function createHeatmapSubpipeline<TInput extends HeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: HeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, personsStore, groupStore, kafkaProducer } = config

    return builder
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep(options.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE))
        .pipe(
            createEventPipelineRunnerHeatmapStep(
                options,
                kafkaProducer,
                teamManager,
                groupTypeManager,
                personsStore,
                groupStore
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
