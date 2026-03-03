import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { AfterBatchStep, BeforeBatchStep } from '../pipelines/batching-pipeline'
import { isOkResult, ok } from '../pipelines/results'

export interface BatchStores {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
}

/**
 * Sets the batch stores in the batch context and adds them to each element's value.
 *
 * Used as the beforeBatch hook in the joined ingestion pipeline to make the
 * stores available to:
 * - Sub-pipeline steps via element values (runtime access)
 * - The afterBatch flush step via the batch context
 */
export function createSetBatchStoresStep<TInput, CInput>(
    config: BatchStores
): BeforeBatchStep<TInput, CInput, BatchStores> {
    return (input) => {
        const elements = input.elements.map((el) => ({
            ...el,
            result: isOkResult(el.result) ? ok({ ...el.result.value, ...config }) : el.result,
        }))
        return Promise.resolve(ok({ elements, batchContext: config }))
    }
}

/**
 * Flushes person and group stores and returns Kafka produce promises as side effects.
 *
 * Used as the afterBatch hook in the joined ingestion pipeline, called once
 * per batch after all events have been processed. Reads the stores from the
 * batch context set by createSetBatchStoresStep.
 *
 * The function:
 * 1. Flushes both person and group stores (blocking DB operations)
 * 2. Creates Kafka produce promises for all store updates
 * 3. Returns those promises as side effects (non-blocking)
 *
 * This allows the pipeline to handle Kafka produces the same way it handles
 * event emission - as side effects that can be scheduled and awaited separately
 * from the consumer commit.
 */
export function createFlushBatchStoresStep<TOutput, COutput>(): AfterBatchStep<TOutput, COutput, BatchStores> {
    return async (input) => {
        const { personsStore, groupStore, kafkaProducer } = input.batchContext

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
                    // Handle message size errors gracefully by capturing a warning
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
