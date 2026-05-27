import { FlushResult } from '../persons/persons-store'

export interface BatchWritingStore {
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
