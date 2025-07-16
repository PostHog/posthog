export class PromiseScheduler {
    public readonly promises: Set<Promise<any>> = new Set()

    public schedule<T>(promise: Promise<T>): Promise<T> {
        this.promises.add(promise)
        void promise.finally(() => this.promises.delete(promise))
        return promise
    }

    public async waitForAll(): Promise<any> {
        return await Promise.all(this.promises)
    }

    public async waitForAllSettled(): Promise<any> {
        return await Promise.allSettled(this.promises)
    }
}
