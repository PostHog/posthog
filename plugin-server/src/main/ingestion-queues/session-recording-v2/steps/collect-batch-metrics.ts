import { Message } from 'node-rdkafka'

import { BatchProcessingStep } from '../../../../ingestion/pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { SessionRecordingIngesterMetrics } from '../metrics'

type Input = { message: Message }

export function createCollectBatchMetricsStep<T extends Input>(): BatchProcessingStep<T, T> {
    return function collectBatchMetricsStep(batch: T[]): Promise<PipelineResult<T>[]> {
        // Calculate batch size metrics
        const batchSize = batch.length
        const batchSizeKb = batch.reduce((acc, item) => (item.message.value?.length ?? 0) + acc, 0) / 1024

        // Observe batch metrics
        SessionRecordingIngesterMetrics.observeKafkaBatchSize(batchSize)
        SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb(batchSizeKb)

        // Aggregate per-partition message counts
        const partitionCounts = batch.reduce(
            (acc, item) => {
                const partition = item.message.partition
                acc[partition] = (acc[partition] || 0) + 1
                return acc
            },
            {} as Record<number, number>
        )

        // Increment per-partition metrics
        Object.entries(partitionCounts).forEach(([partition, count]) => {
            SessionRecordingIngesterMetrics.incrementMessageReceived(parseInt(partition), count)
        })

        // Return ok for each item in the batch (passthrough)
        return Promise.resolve(batch.map((item) => ok(item)))
    }
}
