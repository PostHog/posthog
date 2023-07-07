import { PluginServerCapabilities, PluginServerMode, PluginsServerConfig, stringToPluginServerMode } from './types'
import { isTestEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode: PluginServerMode | null = config.PLUGIN_SERVER_MODE
        ? stringToPluginServerMode[config.PLUGIN_SERVER_MODE]
        : null
    const sharedCapabilities = !isTestEnv() ? { http: true } : {}

    switch (mode) {
        case null:
            return {
                mmdb: true,
                ingestion: true,
                ingestionOverflow: true,
                pluginScheduledTasks: true,
                processPluginJobs: true,
                processAsyncHandlers: true,
                sessionRecordingIngestion: true,
                sessionRecordingBlobIngestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.ingestion:
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                mmdb: true,
                ingestion: true,
                sessionRecordingIngestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.ingestion_overflow:
            return {
                mmdb: true,
                ingestionOverflow: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.analytics_ingestion:
            return {
                mmdb: true,
                ingestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.recordings_ingestion:
            return {
                sessionRecordingIngestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.recordings_blob_ingestion:
            return {
                sessionRecordingBlobIngestion: true,
                ...sharedCapabilities,
            }

        case PluginServerMode.plugins_async:
            return {
                mmdb: true,
                processPluginJobs: true,
                processAsyncHandlers: true,
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.plugins_exports:
            return {
                mmdb: true,
                processAsyncHandlers: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.async_onevent:
            return {
                mmdb: true,
                processAsyncOnEventHandlers: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.async_webhooks:
            return {
                mmdb: true,
                processAsyncWebhooksHandlers: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.jobs:
            return {
                mmdb: true,
                processPluginJobs: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.scheduler:
            return {
                mmdb: true,
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
    }
}
