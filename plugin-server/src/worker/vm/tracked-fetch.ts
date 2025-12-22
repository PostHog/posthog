import { Counter } from 'prom-client'

import { PluginConfig } from '~/types'
import { FetchOptions, legacyFetch } from '~/utils/request'

const vmFetchCounter = new Counter({
    name: 'vm_fetches_total',
    help: 'Count of fetch requests in the VM',
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
    const pluginId = pluginConfig.id.toString()
    const pluginConfigName = pluginConfig.plugin?.name ?? 'unknown'

    try {
        vmFetchTracker.trackRequest(pluginId, {
            url,
            method: fetchParams?.method ?? 'GET',
            body: fetchParams?.body,
        })
        const response = await legacyFetch(url, fetchParams)
        vmFetchCounter
            .labels({
                plugin_id: pluginId,
                plugin_config: pluginConfigName,
                status: response.status.toString(),
            })
            .inc()
        return response
    } catch (error) {
        vmFetchCounter
            .labels({
                plugin_id: pluginId,
                plugin_config: pluginConfigName,
                status: 'unknown',
            })
            .inc()
        throw error
    }
}
