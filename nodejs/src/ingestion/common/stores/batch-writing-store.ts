import { FlushResult } from '~/ingestion/common/persons/persons-store'

export interface BatchWritingStoreFlushStats {
    dirtyEntryCount: number
    referencedBatchCount: number
    cacheEntryCount: number
}

export interface BatchWritingStore<TFlushResult = FlushResult> {
    /*
     * Returns a point-in-time summary of entries that would be captured by
     * flush(), plus the batch IDs that currently reference those dirty entries.
     */
    getFlushStats(): BatchWritingStoreFlushStats

    /*
     * Flushes all batch data that needs to be written.
     *
     * The person store returns Kafka message descriptors (`FlushResult`) that
     * the flush step turns into produce promises. The group store owns its own
     * ClickHouse group outputs, so it returns already-built produce promises
     * (`Promise<unknown>`) that the flush step attaches directly as side effects.
     */
    flush(): Promise<TFlushResult[]>

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
