type QueuedCallback<R> = {
    callback: () => Promise<R>
    resolve: (value: R) => void
    reject: (error: unknown) => void
}

export class PromiseQueue<R> {
    private callbackQueue: QueuedCallback<R>[] = []
    private isExecuting = false

    constructor() {}

    public async add(callback: () => Promise<R>): Promise<R> {
        return new Promise<R>((resolve, reject) => {
            this.callbackQueue.push({ callback, resolve, reject })
            process.nextTick(() => this.processNextCallback())
        })
    }

    private async processNextCallback(): Promise<void> {
        if (this.isExecuting || this.callbackQueue.length === 0) {
            return
        }

        this.isExecuting = true
        const { callback, resolve, reject } = this.callbackQueue.shift()!

        try {
            const result = await callback()
            resolve(result)
        } catch (error) {
            reject(error)
        } finally {
            this.isExecuting = false
            if (this.callbackQueue.length > 0) {
                process.nextTick(() => this.processNextCallback())
            }
        }
    }
}
