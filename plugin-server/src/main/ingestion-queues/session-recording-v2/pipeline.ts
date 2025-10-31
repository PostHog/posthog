import { Message } from 'node-rdkafka'

import { BatchPipeline } from '../../../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../../../ingestion/pipelines/builders'
import { PipelineConfig } from '../../../ingestion/pipelines/result-handling-pipeline'
import { EventHeaders } from '../../../types'
import { createCollectBatchMetricsStep } from './steps/collect-batch-metrics'
import { createParseHeadersStep } from './steps/parse-headers'

export function createSessionRecordingPipeline(
    config: PipelineConfig
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
                )
            )
            .handleResults(config)
            .handleSideEffects(config.promiseScheduler, { await: false })

            .build()
    )
}
