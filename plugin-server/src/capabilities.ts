import { PluginServerCapabilities, PluginsServerConfig } from './types'
import { determineNodeEnv, NodeEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode = config.PLUGIN_SERVER_MODE
    const sharedCapabilities = determineNodeEnv() !== NodeEnv.Test ? { http: true } : {}

    switch (mode) {
        case null:
            return {
                ingestion: true,
                pluginScheduledTasks: true,
                processJobs: true,
                processAsyncHandlers: true,
                ...sharedCapabilities,
            }
        case 'ingestion':
            return { ingestion: true, ...sharedCapabilities }
        case 'async':
            return { pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true, ...sharedCapabilities }
    }
}
