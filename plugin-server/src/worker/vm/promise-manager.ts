import { StatsD } from 'hot-shots'
import { threadId } from 'node:worker_threads'

import { PluginsServerConfig } from '../../types'

export class PromiseManager {
    pendingPromises: Set<Promise<any>>
    config: PluginsServerConfig
    statsd?: StatsD
    instanceId: string

    constructor(config: PluginsServerConfig, statsd?: StatsD, instanceId = '') {
        this.pendingPromises = new Set()
        this.config = config
        this.statsd = statsd
        this.instanceId = instanceId
    }

    public trackPromise(promise: Promise<any>): void {
        if (typeof promise === 'undefined') {
            return
        }

        this.pendingPromises.add(promise)

        promise.finally(() => {
            this.pendingPromises.delete(promise)
        })

        this.statsd?.increment('promise_manager_promises_tracked', {
            instanceId: this.instanceId,
            threadId: threadId ? String(threadId) : 'MAIN',
        })
    }

    public async awaitPromisesIfNeeded(): Promise<void> {
        while (this.pendingPromises.size > this.config.MAX_PENDING_PROMISES_PER_WORKER) {
            await Promise.race(this.pendingPromises)
            this.statsd?.increment('promise_manager_promises_awaited', {
                instanceId: this.instanceId,
                threadId: threadId ? String(threadId) : 'MAIN',
            })
        }
    }
}
