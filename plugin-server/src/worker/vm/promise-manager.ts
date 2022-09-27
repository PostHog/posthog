import { StatsD } from 'hot-shots'

import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig
    statsd?: StatsD

    constructor(config: PluginsServerConfig, statsd?: StatsD) {
        this.pendingPromises = new Set()
        this.config = config
        this.statsd = statsd
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
            this.statsd?.increment('worker_promise_manager_promises_awaited')
        }
    }
}
