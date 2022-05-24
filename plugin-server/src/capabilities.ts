import { PluginServerCapabilities, PluginsServerConfig } from './types'
import { determineNodeEnv, NodeEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode = config.PLUGIN_SERVER_MODE
    const http = determineNodeEnv() !== NodeEnv.Test

    if (mode === null) {
        return { ingestion: true, pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true, http }
    } else if (mode === 'ingestion') {
        return { ingestion: true, http }
    } else {
        // if (mode === 'async')
        return { pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true, http }
    }
}
