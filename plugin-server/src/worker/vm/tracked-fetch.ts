import { Counter } from 'prom-client'

import { PluginConfig } from '~/types'
import { FetchOptions, legacyFetch } from '~/utils/request'

const vmFetchCounter = new Counter({
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
        vmFetchCounter
            .labels({
                plugin_id: pluginConfig.id.toString(),
                plugin_config: pluginConfig.plugin?.name ?? 'unknown',
                status: response.status.toString(),
            })
            .inc()
        return response
    } catch (error) {
        vmFetchCounter
            .labels({
                plugin_id: pluginConfig.id.toString(),
                plugin_config: pluginConfig.plugin?.name ?? 'unknown',
                status: 'unknown',
            })
            .inc()
        throw error
    }
}
