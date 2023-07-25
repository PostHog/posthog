import { StatsD } from 'hot-shots'

import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig
    statsd?: StatsD

    constructor(config: PluginsServerConfig, statsd?: StatsD) {
        this.pendingPromises = new Set()
        this.config = config
        this.statsd = statsd
    }

    public trackPromise(promise: Promise<any>, key: string): void {
        if (typeof promise === 'undefined') {
            return
        }

        status.info('🤝', `Tracking promise ${key} count = ${this.pendingPromises.size}`)
        this.statsd?.increment(`worker_promise_manager_promise_start`, { key })
        this.pendingPromises.add(promise)

        promise.finally(() => {
            this.pendingPromises.delete(promise)
        })
        status.info('✅', `Tracking promise finished ${key}`)
        this.statsd?.increment(`worker_promise_manager_promise_end`, { key })
    }

    public async awaitPromisesIfNeeded(): Promise<void> {
        const startTime = performance.now()
        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            status.info('🤝', `looping in awaitPromise since ${startTime} count = ${this.pendingPromises.size}`)
            await Promise.race(this.pendingPromises)
            this.statsd?.increment('worker_promise_manager_promises_awaited')
        }
        status.info('🕐', `Finished awaiting promises ${performance.now() - startTime}`)
    }
}
