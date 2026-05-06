import { MessageSizeTooLarge } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonOutputs } from '../../worker/ingestion/persons/person-context'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { emitIngestionWarning } from '../common/ingestion-warnings'
import { AfterBatchStep } from '../pipelines/batching-pipeline'
import { ok } from '../pipelines/results'

export interface FlushBatchStoresStepConfig {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    outputs: PersonOutputs
}

/**
 * AfterBatch hook that flushes person and group stores and returns
 * Kafka produce promises as side effects.
 *
 * Called once per batch after all events have been processed.
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
 * @param config.outputs - Output producer for sending store updates
 *
 * @returns An afterBatch step that flushes both stores
 */
export function createFlushBatchStoresStep<TOutput, COutput, CBatch, R extends string = never>(
    config: FlushBatchStoresStepConfig
): AfterBatchStep<TOutput, COutput, CBatch, R> {
    const { personsStore, groupStore, outputs } = config

    return async function flushBatchStoresStep(input) {
        try {
            // Flush both stores in parallel (DB operations, still blocking)
            const [_groupResults, personsStoreMessages] = await Promise.all([groupStore.flush(), personsStore.flush()])

            logger.info('🔄', 'flushBatchStoresStep: Flushed stores', {
                batchSize: input.elements.length,
                personStoreMessageCount: personsStoreMessages.length,
            })

            // Create Kafka produce promises for all person/group store updates
            const producePromises = createProducePromises(personsStoreMessages, outputs)

            // Report metrics for this batch
            personsStore.reportBatch()
            groupStore.reportBatch()

            // Reset stores for next batch
            personsStore.reset()
            groupStore.reset()

            return ok({ elements: input.elements, batchContext: input.batchContext }, producePromises)
        } catch (error) {
            // If flush fails, the error will bubble up and fail the entire batch
            // This maintains the existing behavior where flush errors are fatal
            logger.error('❌', 'flushBatchStoresStep: Failed to flush stores', {
                error,
                batchSize: input.elements.length,
            })
            throw error
        }
    }
}

/**
 * Creates Kafka produce promises for all person store flush results.
 * These promises handle errors appropriately:
 * - MessageSizeTooLarge: Emits ingestion warning (non-fatal)
 * - Other errors: Propagated to fail the side effect
 */
function createProducePromises(personsStoreMessages: FlushResult[], outputs: PersonOutputs): Promise<unknown>[] {
    const promises: Promise<unknown>[] = []

    for (const record of personsStoreMessages) {
        for (const message of record.messages) {
            const promise = outputs
                .produce(message.output, {
                    key: null,
                    value: message.value,
                    teamId: record.teamId,
                })
                .catch((error) => {
                    // Handle message size errors gracefully by capturing a warning
                    if (error instanceof MessageSizeTooLarge) {
                        logger.warn('🪣', 'flushBatchStoresStep: Message size too large', {
                            output: message.output,
                            teamId: record.teamId,
                            distinctId: record.distinctId,
                            uuid: record.uuid,
                        })
                        return emitIngestionWarning(outputs, record.teamId, 'message_size_too_large', {
                            eventUuid: record.uuid,
                            distinctId: record.distinctId,
                            step: 'flushBatchStoresStep',
                        })
                    } else {
                        // Other errors should fail the side effect
                        logger.error('❌', 'flushBatchStoresStep: Failed to produce message', {
                            error,
                            output: message.output,
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
