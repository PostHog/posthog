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
                eventsIngestionPipelines: true, // with null PluginServerMode we run all of them
                processAsyncOnEventHandlers: true,
                processAsyncWebhooksHandlers: true,
                sessionRecordingBlobIngestion: true,
                sessionRecordingBlobOverflowIngestion: config.SESSION_RECORDING_OVERFLOW_ENABLED,
                appManagementSingleton: true,
                preflightSchedules: true,
                cdpProcessedEvents: true,
                cdpFunctionCallbacks: true,
                cdpCyclotronWorker: true,
                syncInlinePlugins: true,
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
        case PluginServerMode.events_ingestion:
            return {
                mmdb: true,
                eventsIngestionPipelines: true,
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
        case PluginServerMode.recordings_blob_ingestion_overflow:
            return {
                sessionRecordingBlobOverflowIngestion: true,
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
        case PluginServerMode.admin:
            return {
                appManagementSingleton: true,
                syncInlinePlugins: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_processed_events:
            return {
                cdpProcessedEvents: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_function_callbacks:
            return {
                cdpFunctionCallbacks: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_cyclotron_worker:
            return {
                cdpCyclotronWorker: true,
                ...sharedCapabilities,
            }
        // This is only for functional tests, which time out if all capabilities are used
        // ideally we'd run just the specific capability needed per test, but that's not easy to do atm
        case PluginServerMode.functional_tests:
            return {
                mmdb: true,
                ingestion: true,
                ingestionHistorical: true,
                eventsIngestionPipelines: true,
                processAsyncOnEventHandlers: true,
                processAsyncWebhooksHandlers: true,
                sessionRecordingBlobIngestion: true,
                appManagementSingleton: true,
                preflightSchedules: true,
                syncInlinePlugins: true,
                ...sharedCapabilities,
            }
    }
}
