import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig

    constructor(config: PluginsServerConfig) {
        this.pendingPromises = new Set()
        this.config = config
    }

    public async trackPromise(promise: Promise<any>): Promise<any> {
        console.log('got a promise!!')
        this.pendingPromises.add(promise)

        console.log(this.pendingPromises)
        promise.finally(() => {
            console.log('deleted')
            this.pendingPromises.delete(promise)
        })

        await this.awaitPromisesIfNeeded()

        return promise
    }

    public async awaitPromisesIfNeeded() {
        console.log('here')
        console.log(this.pendingPromises)

        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            console.log('loopidy loop')
            await Promise.any(this.pendingPromises)
        }
    }
}
