import { PluginServerCapabilities, PluginsServerConfig } from './types'
import { isTestEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode = config.PLUGIN_SERVER_MODE
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
        case 'ingestion':
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                mmdb: true,
                ingestion: true,
                sessionRecordingIngestion: true,
                ...sharedCapabilities,
            }
        case 'ingestion-overflow':
            return {
                mmdb: true,
                ingestionOverflow: true,
                ...sharedCapabilities,
            }
        case 'analytics-ingestion':
            return {
                mmdb: true,
                ingestion: true,
                ...sharedCapabilities,
            }
        case 'recordings-ingestion':
            return {
                sessionRecordingIngestion: true,
                ...sharedCapabilities,
            }
        case 'recordings-blob-ingestion':
            return {
                sessionRecordingBlobIngestion: true,
                ...sharedCapabilities,
            }

        case 'async':
            return {
                mmdb: true,
                processPluginJobs: true,
                processAsyncHandlers: true,
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
        case 'exports':
            return {
                mmdb: true,
                processAsyncHandlers: true,
                ...sharedCapabilities,
            }
        case 'async-onevent':
            return {
                mmdb: true,
                processAsyncOnEventHandlers: true,
                ...sharedCapabilities,
            }
        case 'async-webhooks':
            return {
                mmdb: true,
                processAsyncWebhooksHandlers: true,
                ...sharedCapabilities,
            }
        case 'jobs': {
            return {
                mmdb: true,
                processPluginJobs: true,
                ...sharedCapabilities,
            }
        }
        case 'scheduler':
            return {
                mmdb: true,
                pluginScheduledTasks: true,
                ...sharedCapabilities,
            }
    }
}
