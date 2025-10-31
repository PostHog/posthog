import { Message } from 'node-rdkafka'

import { BatchPipeline } from '../../../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../../../ingestion/pipelines/builders'
import { PipelineConfig } from '../../../ingestion/pipelines/result-handling-pipeline'
import { createCollectBatchMetricsStep } from './steps/collect-batch-metrics'

export function createSessionRecordingPipeline(
    _config: PipelineConfig
): BatchPipeline<{ message: Message }, { message: Message }, { message: Message }> {
    return (
        newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
            // Step 0: Collect batch metrics (batch-level)
            .pipeBatch(createCollectBatchMetricsStep())

            .build()
    )
}
