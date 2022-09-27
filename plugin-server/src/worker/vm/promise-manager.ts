import { StatsD } from 'hot-shots'
import { isMainThread } from 'worker_threads'

import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig
    statsd?: StatsD
    maxPromises: number

    constructor(config: PluginsServerConfig, statsd?: StatsD) {
        this.pendingPromises = new Set()
        this.config = config
        this.statsd = statsd
        this.maxPromises = isMainThread
            ? this.config.MAX_PENDING_PROMISES_MAIN_THREAD
            : this.config.MAX_PENDING_PROMISES_PER_WORKER
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
        while (this.pendingPromises.size > this.maxPromises) {
            await Promise.race(this.pendingPromises)
            this.statsd?.increment('worker_promise_manager_promises_awaited')
        }
    }
}
