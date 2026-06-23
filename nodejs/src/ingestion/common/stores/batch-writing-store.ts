import { FlushResult } from '~/ingestion/common/persons/persons-store'

export interface BatchWritingStoreFlushStats {
    dirtyEntryCount: number
    referencedBatchCount: number
    cacheEntryCount: number
}

export interface BatchWritingStore {
    /*
     * Returns a point-in-time summary of entries that would be captured by
     * flush(), plus the batch IDs that currently reference those dirty entries.
     */
    getFlushStats(): BatchWritingStoreFlushStats

    /*
     * Flushes all batch data that needs to be written
     * Returns Kafka messages that need to be sent
     */
    flush(): Promise<FlushResult[]>

    /*
     * Releases cache entries associated with the given batch ID.
     * Uses reference counting so entries shared across concurrent batches
     * are only evicted when all referencing batches have completed.
     */
    releaseBatch(batchId: number): void

    /*
     * Stops background work and flushes remaining metrics. Called on graceful shutdown.
     */
    shutdown(): Promise<void>
}
