import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { createDisablePersonProcessingStep } from '../ingestion/event-processing/disable-person-processing-step'
import { createEventPipelineRunnerHeatmapStep } from '../ingestion/event-processing/event-pipeline-runner-heatmap-step'
import { createExtractHeatmapDataStep } from '../ingestion/event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../ingestion/event-processing/normalize-event-step'
import { createSkipEmitEventStep } from '../ingestion/event-processing/skip-emit-event-step'
import { BatchPipeline } from '../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../ingestion/pipelines/builders'
import { PipelineConfig } from '../ingestion/pipelines/result-handling-pipeline'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub } from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { applyPreprocessingSubpipeline } from './preprocessing-subpipeline'

export interface HeatmapPipelineConfig {
    hub: Hub
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    hogTransformer: HogTransformerService
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
}

export type HeatmapPipelineInput = { message: Message }
export type HeatmapPipelineOutput = void
export type HeatmapPipelineContext = { message: Message }

/**
 * Creates the heatmap event pipeline that processes $$heatmap events.
 * This pipeline:
 * - Runs preprocessing subpipeline (validation, enrichment, team resolution)
 * - Disables person processing (heatmap events don't update persons)
 * - Normalizes the event
 * - Runs the heatmap-specific event pipeline runner
 * - Extracts heatmap data and sends it to the heatmap topic
 * - Skips emitting to the regular events topic (heatmap events are not stored in the events table)
 */
export function createHeatmapPipeline(
    config: HeatmapPipelineConfig
): BatchPipeline<HeatmapPipelineInput, HeatmapPipelineOutput, HeatmapPipelineContext> {
    const pipelineConfig: PipelineConfig = {
        kafkaProducer: config.kafkaProducer,
        dlqTopic: config.dlqTopic,
        promiseScheduler: config.promiseScheduler,
    }

    const builder = newBatchPipelineBuilder<HeatmapPipelineInput, HeatmapPipelineContext>()

    const preprocessed = applyPreprocessingSubpipeline(builder, {
        hub: config.hub,
        kafkaProducer: config.kafkaProducer,
        dlqTopic: config.dlqTopic,
        promiseScheduler: config.promiseScheduler,
        eventIngestionRestrictionManager: config.eventIngestionRestrictionManager,
        overflowEnabled: config.overflowEnabled,
        overflowTopic: config.overflowTopic,
        preservePartitionLocality: config.preservePartitionLocality,
    })

    return (
        preprocessed
            // TODO: We want a per-distinct-id concurrent pipeline here, but it's not implemented yet.
            // For now, we use messageAware -> teamAware -> sequentially to process events.
            .messageAware((builder) =>
                builder
                    .teamAware((teamBuilder) =>
                        // We process the events for the distinct id sequentially to provide ordering guarantees.
                        teamBuilder.sequentially((seq) =>
                            seq.retry(
                                (retry) =>
                                    retry
                                        .pipe(createDisablePersonProcessingStep())
                                        .pipe(createNormalizeEventStep(config.hub))
                                        .pipe(createEventPipelineRunnerHeatmapStep(config.hub, config.hogTransformer))
                                        .pipe(
                                            createExtractHeatmapDataStep({
                                                kafkaProducer: config.kafkaProducer,
                                                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC:
                                                    config.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                                            })
                                        )
                                        .pipe(createSkipEmitEventStep()),
                                {
                                    tries: 3,
                                    sleepMs: 100,
                                }
                            )
                        )
                    )
                    .handleIngestionWarnings(config.kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(config.promiseScheduler, { await: false })
            .gather()
            .build()
    )
}
