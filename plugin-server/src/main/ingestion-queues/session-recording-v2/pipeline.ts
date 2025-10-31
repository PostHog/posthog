import { Message } from 'node-rdkafka'

import { BatchPipeline } from '../../../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../../../ingestion/pipelines/builders'
import { PipelineConfig } from '../../../ingestion/pipelines/result-handling-pipeline'
import { EventHeaders } from '../../../types'
import { EventIngestionRestrictionManager } from '../../../utils/event-ingestion-restriction-manager'
import { createApplyDropRestrictionsStep } from './steps/apply-drop-restrictions'
import { createApplyOverflowRestrictionsStep } from './steps/apply-overflow-restrictions'
import { createCollectBatchMetricsStep } from './steps/collect-batch-metrics'
import { createParseHeadersStep } from './steps/parse-headers'

export interface SessionRecordingPipelineConfig extends PipelineConfig {
    restrictionManager: EventIngestionRestrictionManager
    overflowTopic: string
    consumeOverflow: boolean
}

export function createSessionRecordingPipeline(
    config: SessionRecordingPipelineConfig
): BatchPipeline<{ message: Message }, { message: Message; headers: EventHeaders }, { message: Message }> {
    return (
        newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
            // Step 0: Collect batch metrics (batch-level)
            .pipeBatch(createCollectBatchMetricsStep())

            .messageAware((builder) =>
                builder.sequentially((b) =>
                    b
                        // Step 1: Parse headers
                        .pipe(createParseHeadersStep())

                        // Step 2a: Apply drop restrictions
                        .pipe(createApplyDropRestrictionsStep(config.restrictionManager))

                        // Step 2b: Apply overflow restrictions
                        .pipe(
                            createApplyOverflowRestrictionsStep(
                                config.restrictionManager,
                                config.overflowTopic,
                                config.consumeOverflow
                            )
                        )
                )
            )
            .handleResults(config)
            .handleSideEffects(config.promiseScheduler, { await: false })

            .build()
    )
}
