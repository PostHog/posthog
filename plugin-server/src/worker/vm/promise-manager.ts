import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig

    constructor(config: PluginsServerConfig) {
        this.pendingPromises = new Set()
        this.config = config
    }

    public async trackPromise(promise: Promise<any>): Promise<any> {
        this.pendingPromises.add(promise)
        promise.finally(() => {
            this.pendingPromises.delete(promise)
        })

        await this.awaitPromisesIfNeeded()

        return promise
    }

    public async awaitPromisesIfNeeded() {
        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            await Promise.any(this.pendingPromises)
        }
    }
}
