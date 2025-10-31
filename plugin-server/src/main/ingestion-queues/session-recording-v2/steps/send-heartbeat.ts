import { BatchProcessingStep } from '../../../../ingestion/pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { KafkaConsumer } from '../../../../kafka/consumer'

/**
 * Send Kafka heartbeat step
 *
 * This is a batch-level step that sends a heartbeat to Kafka to keep the connection alive
 * during long-running batch processing operations.
 *
 * This step passes through its input unchanged and should be called:
 * - At the beginning of batch processing (Step 0)
 * - Before flushing (Step 8) - as flush operations can be slow
 */
export function createSendHeartbeatStep<T>(kafkaConsumer: KafkaConsumer): BatchProcessingStep<T, T> {
    return function sendHeartbeatStep(batch: T[]): Promise<PipelineResult<T>[]> {
        // Send heartbeat to keep Kafka connection alive
        kafkaConsumer.heartbeat()

        // Pass through input unchanged
        return Promise.resolve(batch.map((item) => ok(item)))
    }
}
