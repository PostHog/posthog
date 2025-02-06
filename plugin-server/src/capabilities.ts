import { Config, PluginServerCapabilities, PluginServerMode, stringToPluginServerMode } from './types'
import { isTestEnv } from './utils/env-utils'

export function getPluginServerCapabilities(config: Config): PluginServerCapabilities {
    const mode: PluginServerMode | null = config.PLUGIN_SERVER_MODE
        ? stringToPluginServerMode[config.PLUGIN_SERVER_MODE]
        : null
    const sharedCapabilities = !isTestEnv() ? { http: true } : {}

    const singleProcessCapabilities: PluginServerCapabilities = {
        mmdb: true,
        sessionRecordingBlobIngestion: true,
        sessionRecordingBlobOverflowIngestion: config.SESSION_RECORDING_OVERFLOW_ENABLED,
        sessionRecordingBlobIngestionV2: true,
        sessionRecordingBlobIngestionV2Overflow: config.SESSION_RECORDING_OVERFLOW_ENABLED,
        appManagementSingleton: true,
        preflightSchedules: true,
        cdpProcessedEvents: true,
        cdpInternalEvents: true,
        cdpCyclotronWorker: true,
        cdpCyclotronWorkerPlugins: true,
        cdpApi: true,
        ...sharedCapabilities,
    }

    switch (mode) {
        case null:
            return {
                ...singleProcessCapabilities,
                ingestionV2Combined: true,
            }

        case PluginServerMode.ingestion_v2:
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                mmdb: true,
                ingestionV2: true,
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
        case PluginServerMode.recordings_blob_ingestion_v2:
            return {
                sessionRecordingBlobIngestionV2: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.recordings_blob_ingestion_v2_overflow:
            return {
                sessionRecordingBlobIngestionV2Overflow: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_processed_events:
            return {
                cdpProcessedEvents: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_internal_events:
            return {
                cdpInternalEvents: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_cyclotron_worker:
            return {
                cdpCyclotronWorker: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_cyclotron_worker_plugins:
            return {
                cdpCyclotronWorkerPlugins: true,
                ...sharedCapabilities,
            }
        case PluginServerMode.cdp_api:
            return {
                cdpApi: true,
                // NOTE: This is temporary until we have removed plugins
                appManagementSingleton: true,
                ...sharedCapabilities,
            }
    }
}
