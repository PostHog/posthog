import { PluginServerCapabilities, PluginsServerConfig } from './types'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode = config.PLUGIN_SERVER_MODE

    if (mode === null) {
        return { ingestion: true, pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true }
    } else if (mode === 'ingestion') {
        return { ingestion: true }
    } else {
        // if (mode === 'async')
        return { pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true }
    }
}
