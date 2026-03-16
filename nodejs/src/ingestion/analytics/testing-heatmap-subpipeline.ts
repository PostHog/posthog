import { PluginEvent } from '~/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { createCheckHeatmapOptInStep } from '../event-processing/check-heatmap-opt-in-step'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface TestingHeatmapSubpipelineInput {
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface TestingHeatmapSubpipelineConfig {
    options: {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    kafkaProducer: KafkaProducerWrapper
}

export function createTestingHeatmapSubpipeline<TInput extends TestingHeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: TestingHeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, kafkaProducer } = config

    // Compared to heatmap-subpipeline.ts:
    // REMOVED: createProcessGroupsStep (creates/updates group records, enriches with group properties)
    return builder
        .pipe(createCheckHeatmapOptInStep())
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep())
        .pipe(createPrepareEventStep())
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createSkipEmitEventStep())
}
