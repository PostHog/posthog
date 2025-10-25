import { Message } from 'node-rdkafka'

import { createHandleClientIngestionWarningStep } from '../ingestion/event-processing/handle-client-ingestion-warning-step'
import { BatchPipeline } from '../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../ingestion/pipelines/builders'
import { PipelineConfig } from '../ingestion/pipelines/result-handling-pipeline'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub } from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { applyPreprocessingSubpipeline } from './preprocessing-subpipeline'

export interface ClientIngestionWarningPipelineConfig {
    hub: Hub
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
}

export type ClientIngestionWarningPipelineInput = { message: Message }
export type ClientIngestionWarningPipelineOutput = void
export type ClientIngestionWarningPipelineContext = { message: Message }

/**
 * Creates the client ingestion warning pipeline that processes $$client_ingestion_warning events.
 * This pipeline:
 * - Runs preprocessing subpipeline (validation, enrichment, team resolution)
 * - Handles client ingestion warning events
 * - Emits warnings to the ingestion warnings system
 * - Does not emit events to ClickHouse (warnings are not stored as regular events)
 */
export function createClientIngestionWarningPipeline(
    config: ClientIngestionWarningPipelineConfig
): BatchPipeline<
    ClientIngestionWarningPipelineInput,
    ClientIngestionWarningPipelineOutput,
    ClientIngestionWarningPipelineContext
> {
    const pipelineConfig: PipelineConfig = {
        kafkaProducer: config.kafkaProducer,
        dlqTopic: config.dlqTopic,
        promiseScheduler: config.promiseScheduler,
    }

    const builder = newBatchPipelineBuilder<
        ClientIngestionWarningPipelineInput,
        ClientIngestionWarningPipelineContext
    >()

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
                        teamBuilder.sequentially((seq) => seq.pipe(createHandleClientIngestionWarningStep()))
                    )
                    .handleIngestionWarnings(config.kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(config.promiseScheduler, { await: false })
            .gather()
            .build()
    )
}
