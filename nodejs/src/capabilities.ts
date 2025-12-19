import { PluginServerCapabilities, PluginServerMode, PluginsServerConfig, stringToPluginServerMode } from './types'

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode: PluginServerMode | null = config.PLUGIN_SERVER_MODE
        ? stringToPluginServerMode[config.PLUGIN_SERVER_MODE]
        : null

    switch (mode) {
        case null:
            return {
                ingestionV2Combined: true,
                sessionRecordingBlobIngestionV2: true,
                sessionRecordingBlobIngestionV2Overflow: config.SESSION_RECORDING_OVERFLOW_ENABLED,
                appManagementSingleton: true,
                cdpProcessedEvents: true,
                cdpDataWarehouseEvents: true,
                cdpPersonUpdates: true,
                cdpInternalEvents: true,
                cdpBatchHogFlow: true,
                cdpCyclotronWorker: true,
                cdpCyclotronWorkerHogFlow: true,
                cdpCyclotronWorkerDelay: true,
                cdpPrecalculatedFilters: true,
                cdpCohortMembership: true,
                cdpApi: true,
                evaluationScheduler: true,
                logsIngestion: true,
            }

        case PluginServerMode.local_cdp:
            return {
                ingestionV2: true,
                cdpProcessedEvents: true,
                cdpDataWarehouseEvents: true,
                cdpPersonUpdates: true,
                cdpInternalEvents: true,
                cdpCyclotronWorker: true,
                cdpBatchHogFlow: true,
                cdpCyclotronWorkerHogFlow: true,
                cdpCyclotronWorkerDelay: true,
                cdpPrecalculatedFilters: true,
                cdpCohortMembership: true,
                cdpApi: true,
            }

        case PluginServerMode.ingestion_v2:
            // NOTE: this mode will be removed in the future and replaced with
            // `analytics-ingestion` and `recordings-ingestion` modes.
            return {
                ingestionV2: true,
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
        case PluginServerMode.cdp_person_updates:
            return {
                cdpPersonUpdates: true,
            }
        case PluginServerMode.cdp_internal_events:
            return {
                cdpInternalEvents: true,
            }
        case PluginServerMode.cdp_cyclotron_worker:
            return {
                cdpCyclotronWorker: true,
            }
        case PluginServerMode.cdp_cyclotron_worker_hogflow:
            return {
                cdpCyclotronWorkerHogFlow: true,
            }
        case PluginServerMode.cdp_cyclotron_worker_delay:
            return {
                cdpCyclotronWorkerDelay: true,
            }
        case PluginServerMode.cdp_precalculated_filters:
            return {
                cdpPrecalculatedFilters: true,
            }
        case PluginServerMode.cdp_cohort_membership:
            return {
                cdpCohortMembership: true,
            }
        case PluginServerMode.cdp_legacy_on_event:
            return {
                cdpLegacyOnEvent: true,
            }
        case PluginServerMode.cdp_api:
            return {
                cdpApi: true,
                // NOTE: This is temporary until we have removed plugins
                appManagementSingleton: true,
            }
        case PluginServerMode.evaluation_scheduler:
            return {
                evaluationScheduler: true,
            }
        case PluginServerMode.ingestion_logs:
            return {
                logsIngestion: true,
            }
        case PluginServerMode.cdp_batch_hogflow_requests:
            return {
                cdpBatchHogFlow: true,
            }
        case PluginServerMode.cdp_data_warehouse_events:
            return {
                cdpDataWarehouseEvents: true,
            }
        case PluginServerMode.recording_api:
            return {
                recordingApi: true,
            }
    }
}
