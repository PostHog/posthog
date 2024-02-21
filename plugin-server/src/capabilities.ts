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
                ingestionHistorical: true,
                pluginScheduledTasks: true,
                processPluginJobs: true,
                processAsyncOnEventHandlers: true,
                processAsyncWebhooksHandlers: true,
                sessionRecordingBlobIngestion: true,
                // TODO: Remove this
                sessionRecordingV3Ingestion: true,
                personOverrides: true,
                appManagementSingleton: true,
                preflightSchedules: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.ingestion:
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                mmdb: true,
                ingestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.ingestion_overflow:
            return {
                mmdb: true,
                ingestionOverflow: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.ingestion_historical:
            return {
                mmdb: true,
                ingestionHistorical: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.analytics_ingestion:
            return {
                mmdb: true,
                ingestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.recordings_blob_ingestion:
            return {
                sessionRecordingBlobIngestion: true,
                ...sharedCapabilities,
            }

        case PluginServerMode.recordings_ingestion_v3:
            return {
                sessionRecordingV3Ingestion: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.async_onevent:
            return {
                processAsyncOnEventHandlers: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.async_webhooks:
            return {
                processAsyncWebhooksHandlers: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.jobs:
            return {
                processPluginJobs: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.scheduler:
            return {
                pluginScheduledTasks: true,
                appManagementSingleton: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.person_overrides:
            return {
                personOverrides: true,
                ...sharedCapabilities,
            }
    }
}
