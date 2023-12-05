import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig

    constructor(config: PluginsServerConfig) {
        this.pendingPromises = new Set()
        this.config = config
    }

    public trackPromise(promise: Promise<any>, key: string): void {
        if (typeof promise === 'undefined') {
            return
        }

        status.info('🤝', `Tracking promise ${key} count = ${this.pendingPromises.size}`)
        this.pendingPromises.add(promise)

        promise.finally(() => {
            this.pendingPromises.delete(promise)
        })
        status.info('✅', `Tracking promise finished ${key}`)
    }

    public async awaitPromisesIfNeeded(): Promise<void> {
        const startTime = performance.now()
        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            status.info('🤝', `looping in awaitPromise since ${startTime} count = ${this.pendingPromises.size}`)
            await Promise.race(this.pendingPromises)
        }
        status.info('🕐', `Finished awaiting promises ${performance.now() - startTime}`)
    }
}
