export interface BatchWritingStore {
    /*
     * Flushes all batch data that needs to be written
     */
    flush(): Promise<void>
}
