import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface FlushBatchStoresStepConfig {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

/**
 * Batch processing step that flushes person and group stores and enqueues
 * Kafka messages using fire-and-forget.
 *
 * This step should be added at the end of the pipeline after all events
 * have been processed but before handleResults/handleSideEffects.
 *
 * The step:
 * 1. Flushes both person and group stores (blocking DB operations)
 * 2. Enqueues Kafka messages into rdkafka's buffer (non-blocking, no delivery report awaiting)
 * 3. Errors are surfaced at batch boundary via flushWithErrors() in awaitScheduledWork
 */
export function createFlushBatchStoresStep<T>(config: FlushBatchStoresStepConfig): BatchProcessingStep<T, void> {
    const { personsStore, groupStore, kafkaProducer } = config

    return async function flushBatchStoresStep(batch: T[]): Promise<PipelineResult<void>[]> {
        if (batch.length === 0) {
            return []
        }

        try {
            // Flush both stores in parallel (DB operations, still blocking)
            const [_groupResults, personsStoreMessages] = await Promise.all([groupStore.flush(), personsStore.flush()])

            logger.info('🔄', 'flushBatchStoresStep: Flushed stores', {
                batchSize: batch.length,
                personStoreMessageCount: personsStoreMessages.length,
            })

            // Fire-and-forget: enqueue all messages into rdkafka's buffer.
            // Errors are surfaced at batch boundary via flushWithErrors() in awaitScheduledWork.
            enqueueStoreMessages(personsStoreMessages, kafkaProducer)

            // Report metrics for this batch
            personsStore.reportBatch()
            groupStore.reportBatch()

            // Reset stores for next batch
            personsStore.reset()
            groupStore.reset()

            return batch.map(() => ok(undefined))
        } catch (error) {
            logger.error('❌', 'flushBatchStoresStep: Failed to flush stores', {
                error,
                batchSize: batch.length,
            })
            throw error
        }
    }
}

/**
 * Enqueues Kafka messages for all person store flush results using fire-and-forget.
 * Messages are buffered in rdkafka and sent at the next batch boundary via flush().
 */
function enqueueStoreMessages(personsStoreMessages: FlushResult[], kafkaProducer: KafkaProducerWrapper): void {
    for (const record of personsStoreMessages) {
        for (const message of record.topicMessage.messages) {
            kafkaProducer.enqueue({
                topic: record.topicMessage.topic,
                key: message.key ? Buffer.from(message.key) : null,
                value: message.value ? Buffer.from(message.value) : null,
                headers: message.headers,
            })
        }
    }
}
