import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { createAddBatchStoresStep } from '../ingestion/event-processing/add-batch-stores-step'
import { createCreateEventStep } from '../ingestion/event-processing/create-event-step'
import { createEmitEventStep } from '../ingestion/event-processing/emit-event-step'
import { createEventPipelineRunnerV1Step } from '../ingestion/event-processing/event-pipeline-runner-v1-step'
import { createExtractHeatmapDataStep } from '../ingestion/event-processing/extract-heatmap-data-step'
import { createNormalizeProcessPersonFlagStep } from '../ingestion/event-processing/normalize-process-person-flag-step'
import { BatchPipeline } from '../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../ingestion/pipelines/builders'
import { PipelineConfig } from '../ingestion/pipelines/result-handling-pipeline'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub } from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { applyPreprocessingSubpipeline } from './preprocessing-subpipeline'

export interface AnalyticsPipelineConfig {
    hub: Hub
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    hogTransformer: HogTransformerService
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
    personStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
}

export type AnalyticsPipelineInput = { message: Message }
export type AnalyticsPipelineOutput = void
export type AnalyticsPipelineContext = { message: Message }

/**
 * Creates the analytics event pipeline that processes regular events.
 * This pipeline:
 * - Runs preprocessing subpipeline (validation, enrichment, team resolution)
 * - Normalizes the processPerson flag
 * - Runs the event through the V1 event pipeline runner (transforms, person processing, etc.)
 * - Extracts heatmap data if present (for backwards compatibility with older clients)
 * - Creates the event structure for ClickHouse
 * - Emits the event to the ClickHouse events topic
 */
export function createAnalyticsPipeline(
    config: AnalyticsPipelineConfig
): BatchPipeline<AnalyticsPipelineInput, AnalyticsPipelineOutput, AnalyticsPipelineContext> {
    const pipelineConfig: PipelineConfig = {
        kafkaProducer: config.kafkaProducer,
        dlqTopic: config.dlqTopic,
        promiseScheduler: config.promiseScheduler,
    }

    const builder = newBatchPipelineBuilder<AnalyticsPipelineInput, AnalyticsPipelineContext>()

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
            .pipeBatch(
                createAddBatchStoresStep({
                    personStore: config.personStore,
                    groupStore: config.groupStore,
                })
            )
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
                                        .pipe(createNormalizeProcessPersonFlagStep())
                                        .pipe(createEventPipelineRunnerV1Step(config.hub, config.hogTransformer))
                                        // TRICKY: Older client versions may still send $heatmap_data as properties on regular events.
                                        // This step extracts and processes that data even though up-to-date clients send dedicated $$heatmap events.
                                        // TODO: Verify if we still receive $heatmap_data on regular events and consider removing this step if not.
                                        .pipe(
                                            createExtractHeatmapDataStep({
                                                kafkaProducer: config.kafkaProducer,
                                                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC:
                                                    config.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                                            })
                                        )
                                        .pipe(createCreateEventStep())
                                        .pipe(
                                            createEmitEventStep({
                                                kafkaProducer: config.kafkaProducer,
                                                clickhouseJsonEventsTopic:
                                                    config.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                                            })
                                        ),
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
