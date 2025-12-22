import { Counter } from 'prom-client'

import { PluginConfig } from '~/types'
import { FetchOptions, legacyFetch } from '~/utils/request'

const vmFetchErrorCounter = new Counter({
    name: 'vm_fetches_total',
    help: 'Count of fetch errors in the VM',
    labelNames: ['plugin_id', 'plugin_config', 'status'],
})

export type MinimalTracked = {
    url: string
    method: string
    body: any
}

export class FetchTracker {
    requests: {
        [id: string]: MinimalTracked[] | undefined
    }
    constructor() {
        this.requests = {}
    }

    trackRequest(id: string, request: MinimalTracked) {
        if (!this.requests[id]) {
            this.requests[id] = []
        }
        this.requests[id]!.push(request)
    }

    clearRequests() {
        this.requests = {}
    }
}

export const vmFetchTracker = new FetchTracker()

export const createVmTrackedFetch = (pluginConfig: PluginConfig) => async (url: string, fetchParams?: FetchOptions) => {
    try {
        vmFetchTracker.trackRequest(pluginConfig.id.toString(), {
            url,
            method: fetchParams?.method ?? 'GET',
            body: fetchParams?.body,
        })
        const response = await legacyFetch(url, fetchParams)
        vmFetchErrorCounter
            .labels(pluginConfig.id.toString(), pluginConfig.plugin?.name ?? 'unknown', response.status.toString())
            .inc()
        return response
    } catch (error) {
        vmFetchErrorCounter.labels(pluginConfig.plugin_id.toString(), pluginConfig.id.toString(), 'unknown').inc()
        throw error
    }
}
