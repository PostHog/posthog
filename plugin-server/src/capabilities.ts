import { Config, PluginServerCapabilities, PluginServerMode, stringToPluginServerMode } from './types'

export function getPluginServerCapabilities(config: Config): PluginServerCapabilities {
    const mode: PluginServerMode | null = config.PLUGIN_SERVER_MODE
        ? stringToPluginServerMode[config.PLUGIN_SERVER_MODE]
        : null

    switch (mode) {
        case null:
            return {
                ingestionV2Combined: true,
                sessionRecordingBlobIngestion: true,
                sessionRecordingBlobOverflowIngestion: config.SESSION_RECORDING_OVERFLOW_ENABLED,
                sessionRecordingBlobIngestionV2: true,
                sessionRecordingBlobIngestionV2Overflow: config.SESSION_RECORDING_OVERFLOW_ENABLED,
                appManagementSingleton: true, // TODO: PURGE
                preflightSchedules: true,
                cdpProcessedEvents: true,
                cdpInternalEvents: true,
                cdpCyclotronWorker: true,
                cdpCyclotronWorkerPlugins: true,
                cdpApi: true,
            }

        case PluginServerMode.ingestion_v2:
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                ingestionV2: true,
            }

        case PluginServerMode.recordings_blob_ingestion:
            return {
                sessionRecordingBlobIngestion: true,
            }
        case PluginServerMode.recordings_blob_ingestion_overflow:
            return {
                sessionRecordingBlobOverflowIngestion: true,
            }
        case PluginServerMode.recordings_blob_ingestion_v2:
            return {
                sessionRecordingBlobIngestionV2: true,
            }
        case PluginServerMode.recordings_blob_ingestion_v2_overflow:
            return {
                sessionRecordingBlobIngestionV2Overflow: true,
            }
        case PluginServerMode.cdp_processed_events:
            return {
                cdpProcessedEvents: true,
            }
        case PluginServerMode.cdp_internal_events:
            return {
                cdpInternalEvents: true,
            }
        case PluginServerMode.cdp_cyclotron_worker:
            return {
                cdpCyclotronWorker: true,
            }
        case PluginServerMode.cdp_cyclotron_worker_plugins:
            return {
                cdpCyclotronWorkerPlugins: true,
            }
        case PluginServerMode.cdp_api:
            return {
                cdpApi: true,
                // NOTE: This is temporary until we have removed plugins
                appManagementSingleton: true,
            }

        default:
            throw new Error(`Unknown plugin server mode: ${mode}`)
    }
}
