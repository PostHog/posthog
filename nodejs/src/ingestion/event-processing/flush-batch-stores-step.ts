import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { AfterBatchStep } from '../pipelines/batching-pipeline'
import { ok } from '../pipelines/results'

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
export function createFlushBatchStoresStep<TOutput, COutput, CBatch>(
    config: FlushBatchStoresStepConfig
): AfterBatchStep<TOutput, COutput, CBatch> {
    const { personsStore, groupStore, kafkaProducer } = config

    return async (input) => {
        try {
            const [_groupResults, personsStoreMessages] = await Promise.all([groupStore.flush(), personsStore.flush()])

            const producePromises = createProducePromises(personsStoreMessages, kafkaProducer)

            personsStore.reportBatch()
            groupStore.reportBatch()

            personsStore.reset()
            groupStore.reset()

            return ok({ elements: input.elements, batchContext: input.batchContext }, producePromises)
        } catch (error) {
            logger.error('❌', 'flushBatchStoresStep: Failed to flush stores', { error })
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
                .catch((error) => {
                    if (error instanceof MessageSizeTooLarge) {
                        logger.warn('🪣', 'flushBatchStoresStep: Message size too large', {
                            topic: record.topicMessage.topic,
                            teamId: record.teamId,
                            distinctId: record.distinctId,
                            uuid: record.uuid,
                        })
                        return captureIngestionWarning(kafkaProducer, record.teamId, 'message_size_too_large', {
                            eventUuid: record.uuid,
                            distinctId: record.distinctId,
                            step: 'flushBatchStoresStep',
                        })
                    } else {
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
