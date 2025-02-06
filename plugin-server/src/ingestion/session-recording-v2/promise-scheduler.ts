export class PromiseScheduler {
    private promises: Set<Promise<any>> = new Set()

    public schedule<T>(promise: Promise<T>): Promise<T> {
        /**
         * Helper to handle graceful shutdowns. Every time we do some work we add a promise to this array and remove it when finished.
         * That way when shutting down we can wait for all promises to finish before exiting.
         */
        this.promises.add(promise)

        // we void the promise returned by finally here to avoid the need to await it
        void promise.finally(() => this.promises.delete(promise))

        return promise
    }

    public async waitForAll(): Promise<PromiseSettledResult<any>[]> {
        return Promise.allSettled(Array.from(this.promises))
    }
}
