import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface FlushBatchStoresStepConfig {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

/**
 * Batch processing step that flushes person and group stores and returns
 * Kafka produce promises as side effects.
 *
 * This step should be added at the end of the pipeline after all events
 * have been processed but before handleResults/handleSideEffects.
 *
 * The step:
 * 1. Flushes both person and group stores (blocking DB operations)
 * 2. Creates Kafka produce promises for all store updates
 * 3. Returns those promises as side effects (non-blocking)
 *
 * This allows the pipeline to handle Kafka produces the same way it handles
 * event emission - as side effects that can be scheduled and awaited separately
 * from the consumer commit.
 *
 * @param config - Configuration containing the stores and Kafka producer
 * @param config.personsStore - The person store (singleton per consumer)
 * @param config.groupStore - The group store (singleton per consumer)
 * @param config.kafkaProducer - Kafka producer for sending store updates
 *
 * @returns A batch processing step that flushes both stores
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

            // Create Kafka produce promises for all person/group store updates
            const producePromises = createProducePromises(personsStoreMessages, kafkaProducer)

            // Report metrics for this batch
            personsStore.reportBatch()
            groupStore.reportBatch()

            // Reset stores for next batch
            personsStore.reset()
            groupStore.reset()

            // Return same number of results as input, all sharing the same side effects
            // This ensures the pipeline correctly handles the batch structure
            return batch.map(() => ok(undefined, producePromises))
        } catch (error) {
            // If flush fails, the error will bubble up and fail the entire batch
            // This maintains the existing behavior where flush errors are fatal
            logger.error('❌', 'flushBatchStoresStep: Failed to flush stores', {
                error,
                batchSize: batch.length,
            })
            throw error
        }
    }
}

/**
 * Creates Kafka produce promises for all person store flush results.
 * These promises handle errors appropriately:
 * - MessageSizeTooLarge: Captures ingestion warning (non-fatal)
 * - Other errors: Propagated to fail the side effect
 */
function createProducePromises(
    personsStoreMessages: FlushResult[],
    kafkaProducer: KafkaProducerWrapper
): Promise<unknown>[] {
    const promises: Promise<unknown>[] = []

    for (const record of personsStoreMessages) {
        for (const message of record.topicMessage.messages) {
            const promise = kafkaProducer
                .produce({
                    topic: record.topicMessage.topic,
                    key: message.key ? Buffer.from(message.key) : null,
                    value: message.value ? Buffer.from(message.value) : null,
                    headers: message.headers,
                })
                .catch(async (error) => {
                    // Handle message size errors gracefully by capturing a warning
                    if (error instanceof MessageSizeTooLarge) {
                        await captureIngestionWarning(kafkaProducer, record.teamId, 'message_size_too_large', {
                            eventUuid: record.uuid,
                            distinctId: record.distinctId,
                        })
                        logger.warn('🪣', 'flushBatchStoresStep: Message size too large', {
                            topic: record.topicMessage.topic,
                            teamId: record.teamId,
                            distinctId: record.distinctId,
                            uuid: record.uuid,
                        })
                    } else {
                        // Other errors should fail the side effect
                        logger.error('❌', 'flushBatchStoresStep: Failed to produce message', {
                            error,
                            topic: record.topicMessage.topic,
                            teamId: record.teamId,
                            distinctId: record.distinctId,
                            uuid: record.uuid,
                        })
                        throw error
                    }
                })

            promises.push(promise)
        }
    }

    return promises
}
