import { Counter } from 'prom-client'

import { PluginConfig } from '~/types'
import { FetchOptions, legacyFetch } from '~/utils/request'

const vmFetchCounter = new Counter({
    name: 'vm_fetches_total',
    help: 'Count of fetch requests in the VM',
    labelNames: ['plugin_id', 'plugin_config', 'status'],
})

export const createVmTrackedFetch = (pluginConfig: PluginConfig) => async (url: string, fetchParams?: FetchOptions) => {
    const pluginId = pluginConfig.id.toString()
    const pluginConfigName = pluginConfig.plugin?.name ?? 'unknown'

    try {
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
