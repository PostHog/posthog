import { FlushResult } from '../persons/persons-store-for-batch'

export interface BatchWritingStore {
    /*
     * Flushes all batch data that needs to be written
     * Returns Kafka messages that need to be sent
     */
    flush(): Promise<FlushResult[]>
}
