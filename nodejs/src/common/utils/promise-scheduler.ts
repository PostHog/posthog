export class PromiseScheduler {
    public readonly promises: Set<Promise<any>> = new Set()

    public schedule<T>(promise: Promise<T>): Promise<T>
    public schedule<T extends readonly [Promise<unknown>, Promise<unknown>, ...Promise<unknown>[]]>(
        ...promises: T
    ): Promise<{ -readonly [K in keyof T]: Awaited<T[K]> }>
    public schedule(...promises: Promise<unknown>[]): Promise<unknown> {
        for (const promise of promises) {
            this.promises.add(promise)
            const cleanup = () => this.promises.delete(promise)
            promise.then(cleanup, cleanup)
        }
        return promises.length === 1 ? promises[0] : Promise.all(promises)
    }

    public async waitForAll() {
        return await Promise.all(this.promises)
    }

    public async waitForAllSettled() {
        return await Promise.allSettled(this.promises)
    }
}
