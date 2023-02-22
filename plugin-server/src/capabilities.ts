import { PluginServerCapabilities, PluginsServerConfig } from './types'
import { isTestEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    // Given the server config, which is largely determined by environment
    // variables, determine which workloads/capabilities this instance of the
    // plugin-server should run.
    //
    // Note that historically we have used `PLUGIN_SERVER_MODE` for determining
    // the workloads we want to run. However, this makes it difficult to roll
    // out changes in a controlled manner, so instead we are moving towards
    // removing this abstraction and instead explicitly specifying the workloads
    // by way of individual environment variables.
    const mode = config.PLUGIN_SERVER_MODE
    const sharedCapabilities = !isTestEnv() ? { http: true } : {}

    let capabilities: PluginServerCapabilities = {
        ...sharedCapabilities,
    }

    if (mode == null) {
        capabilities = {
            ...capabilities,
            ingestion: true,
            ingestionOverflow: true,
            pluginScheduledTasks: true,
            processPluginJobs: true,
            processAsyncHandlers: true,
            sessionRecordingIngestion: true,
        }
    } else if (mode === 'ingestion') {
        capabilities = {
            ...capabilities,
            ingestion: true,
        }
    } else if (mode === 'ingestion-overflow') {
        capabilities = {
            ...capabilities,
            ingestionOverflow: true,
        }
    } else if (mode === 'async') {
        capabilities = {
            ...capabilities,
            processPluginJobs: true,
            processAsyncHandlers: true,
            pluginScheduledTasks: true,
        }
    } else if (mode === 'exports') {
        capabilities = {
            ...capabilities,
            processAsyncHandlers: true,
        }
    } else if (mode === 'jobs') {
        capabilities = {
            ...capabilities,
            processPluginJobs: true,
        }
    } else if (mode === 'scheduler') {
        capabilities = {
            ...capabilities,
            pluginScheduledTasks: true,
        }
    }

    if (process.env.SESSION_RECORDING_PROCESSING_ENABLED) {
        // If the reference env. var. is set, use it to override whatever we
        // determined from the `PLUGIN_SERVER_MODE` env. var.
        capabilities = {
            ...capabilities,
            sessionRecordingIngestion: process.env.SESSION_RECORDING_PROCESSING_ENABLED === 'true',
        }
    }

    return capabilities
}
