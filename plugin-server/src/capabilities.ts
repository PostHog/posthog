import { PluginServerCapabilities, PluginsServerConfig } from './types'
import { isTestEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode = config.PLUGIN_SERVER_MODE
    const sharedCapabilities = !isTestEnv() ? { http: true } : {}

    switch (mode) {
        case null:
            return {
                ingestion: true,
                ingestionOverflow: true,
                pluginScheduledTasks: true,
                processPluginJobs: true,
                processAsyncHandlers: true,
                ...sharedCapabilities,
            }
        case 'ingestion':
            return { ingestion: true, ...sharedCapabilities }
        case 'ingestion-overflow':
            return { ingestionOverflow: true, ...sharedCapabilities }
        case 'async':
            return {
                processPluginJobs: true,
                processAsyncHandlers: true,
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
        case 'exports':
            return {
                processAsyncHandlers: true,
                ...sharedCapabilities,
            }
        case 'jobs': {
            return {
                processPluginJobs: true,
                ...sharedCapabilities,
            }
        }
        case 'scheduler':
            return {
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
    }
}
