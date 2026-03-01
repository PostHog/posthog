import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { BatchResult } from '../pipelines/batching-pipeline'

export interface FlushBatchStoresStepConfig {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

/**
 * Flushes person and group stores and returns Kafka produce promises as side effects.
 *
 * Used as the afterBatch hook in the joined ingestion pipeline, called once
 * per batch after all events have been processed.
 *
 * The function:
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
 */
export async function flushBatchStores(config: FlushBatchStoresStepConfig): Promise<BatchResult<void>> {
    const { personsStore, groupStore, kafkaProducer } = config

    try {
        // Flush both stores in parallel (DB operations, still blocking)
        const [_groupResults, personsStoreMessages] = await Promise.all([groupStore.flush(), personsStore.flush()])

        // Create Kafka produce promises for all person/group store updates
        const producePromises = createProducePromises(personsStoreMessages, kafkaProducer)

        // Report metrics for this batch
        personsStore.reportBatch()
        groupStore.reportBatch()

        // Reset stores for next batch
        personsStore.reset()
        groupStore.reset()

        return { elements: undefined, sideEffects: producePromises }
    } catch (error) {
        // If flush fails, the error will bubble up and fail the entire batch
        // This maintains the existing behavior where flush errors are fatal
        logger.error('❌', 'flushBatchStores: Failed to flush stores', { error })
        throw error
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
                .catch((error) => {
                    // Handle message size errors gracefully by capturing a warning
                    if (error instanceof MessageSizeTooLarge) {
                        logger.warn('🪣', 'flushBatchStores: Message size too large', {
                            topic: record.topicMessage.topic,
                            teamId: record.teamId,
                            distinctId: record.distinctId,
                            uuid: record.uuid,
                        })
                        return captureIngestionWarning(kafkaProducer, record.teamId, 'message_size_too_large', {
                            eventUuid: record.uuid,
                            distinctId: record.distinctId,
                            step: 'flushBatchStores',
                        })
                    } else {
                        // Other errors should fail the side effect
                        logger.error('❌', 'flushBatchStores: Failed to produce message', {
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
