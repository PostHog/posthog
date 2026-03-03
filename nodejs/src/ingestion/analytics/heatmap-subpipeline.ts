import { PluginEvent } from '~/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { createCheckHeatmapOptInStep } from '../event-processing/check-heatmap-opt-in-step'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
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
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

export function createHeatmapSubpipeline<TInput extends HeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: HeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, groupStore, kafkaProducer } = config

    return builder
        .pipe(createCheckHeatmapOptInStep())
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep())
        .pipe(createPrepareEventStep(teamManager, groupTypeManager, groupStore, options))
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createSkipEmitEventStep())
}
