import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { PersonOutputs } from '~/ingestion/common/persons/person-context'
import { FlushResult, PersonsStore } from '~/ingestion/common/persons/persons-store'
import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import {
    batchStoreFlushCacheEntriesHistogram,
    batchStoreFlushDirtyEntriesHistogram,
    batchStoreFlushKafkaMessagesHistogram,
    batchStoreFlushLatencyHistogram,
    batchStoreFlushOperationsCounter,
    batchStoreFlushReferencedBatchesHistogram,
    batchStoreFlushResultRecordsHistogram,
    batchStoreFlushTriggerBatchSizeHistogram,
} from '~/ingestion/common/stores/metrics'
import { AfterBatchStep } from '~/ingestion/framework/batching-pipeline'
import { ok } from '~/ingestion/framework/results'

export interface FlushBatchStoresStepConfig {
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    outputs: PersonOutputs
}

type BatchStoreName = 'person' | 'group'

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
        batchStoreFlushTriggerBatchSizeHistogram.observe(input.elements.length)

        try {
            // Flush both stores in parallel (DB operations, still blocking).
            // Stores own their own metric-emission lifecycle (periodic timer
            // started in their constructors, drained by shutdown()), so this
            // step no longer touches reset/reportBatch — caches persist across
            // batches by design under concurrentBatches > 1.
            //
            // The person store returns Kafka message descriptors that we turn
            // into produce promises here. The group store owns its ClickHouse
            // group outputs, so it returns already-started produce promises
            // that we attach directly as side effects.
            const [groupProducePromises, personsStoreMessages] = await Promise.all([
                flushStore('group', groupStore, (results) => results.length),
                flushStore('person', personsStore, countFlushResultMessages),
            ])

            const personStoreKafkaMessageCount = countFlushResultMessages(personsStoreMessages)

            logger.info('🔄', 'flushBatchStoresStep: Flushed stores', {
                batchSize: input.elements.length,
                personStoreMessageCount: personsStoreMessages.length,
                personStoreKafkaMessageCount,
                groupStoreMessageCount: groupProducePromises.length,
            })

            const producePromises = [...groupProducePromises, ...createProducePromises(personsStoreMessages, outputs)]

            return ok(input, producePromises)
        } catch (error) {
            // If flush fails, the error will bubble up and fail the entire batch
            // This maintains the existing behavior where flush errors are fatal
            logger.error('❌', 'flushBatchStoresStep: Failed to flush stores', {
                error,
                batchSize: input.elements.length,
            })
            throw error
        } finally {
            // Always release the batch to prevent refcount leaks, even on flush failure.
            personsStore.releaseBatch(input.batchId)
            groupStore.releaseBatch(input.batchId)
        }
    }
}

async function flushStore<T>(
    store: BatchStoreName,
    batchWritingStore: BatchWritingStore<T>,
    countMessages: (results: T[]) => number
): Promise<T[]> {
    const flushStats = batchWritingStore.getFlushStats()
    batchStoreFlushDirtyEntriesHistogram.observe({ store }, flushStats.dirtyEntryCount)
    batchStoreFlushReferencedBatchesHistogram.observe({ store }, flushStats.referencedBatchCount)
    batchStoreFlushCacheEntriesHistogram.observe({ store }, flushStats.cacheEntryCount)

    const flushStartTime = performance.now()
    try {
        const flushResults = await batchWritingStore.flush()
        const latencySeconds = (performance.now() - flushStartTime) / 1000
        batchStoreFlushLatencyHistogram.observe({ store, outcome: 'success' }, latencySeconds)
        batchStoreFlushOperationsCounter.inc({ store, outcome: 'success' })
        batchStoreFlushResultRecordsHistogram.observe({ store }, flushResults.length)
        batchStoreFlushKafkaMessagesHistogram.observe({ store }, countMessages(flushResults))
        return flushResults
    } catch (error) {
        const latencySeconds = (performance.now() - flushStartTime) / 1000
        batchStoreFlushLatencyHistogram.observe({ store, outcome: 'error' }, latencySeconds)
        batchStoreFlushOperationsCounter.inc({ store, outcome: 'error' })
        throw error
    }
}

function countFlushResultMessages(flushResults: FlushResult[]): number {
    return flushResults.reduce((count, record) => count + record.messages.length, 0)
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
                        return emitIngestionWarning(outputs, record.teamId, {
                            type: 'message_size_too_large',
                            details: {
                                // FlushResult.uuid is the person uuid, not the event uuid
                                personId: record.uuid,
                                distinctId: record.distinctId,
                                step: 'flushBatchStoresStep',
                            },
                            pipelineStep: 'flush',
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
