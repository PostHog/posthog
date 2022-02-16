import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig

    constructor(config: PluginsServerConfig) {
        this.pendingPromises = new Set()
        this.config = config
    }

    public trackPromise(promise: Promise<any>): void {
        if (typeof promise === 'undefined') {
            return
        }

        this.pendingPromises.add(promise)

        promise.finally(() => {
            this.pendingPromises.delete(promise)
        })
    }

    public async awaitPromisesIfNeeded(): Promise<void> {
        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            await Promise.race(this.pendingPromises)
        }
    }
}
