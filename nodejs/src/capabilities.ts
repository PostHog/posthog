import { PluginServerCapabilities, PluginServerMode, PluginsServerConfig, stringToPluginServerMode } from './types'

// =============================================================================
// Capability Groups for Local Development
// These can be combined via hogli dev:setup to reduce event loop contention and memory overhead
// =============================================================================

/** CDP - destinations, webhooks, and realtime alerts */
export const CAPABILITIES_CDP: PluginServerCapabilities = {
    cdpProcessedEvents: true,
    cdpPersonUpdates: true,
    cdpInternalEvents: true,
    cdpCyclotronWorker: true,
    cdpCyclotronShadowWorker: true,
    cdpApi: true,
    appManagementSingleton: true,
    cdpDataWarehouseEvents: false, // Not yet fully developed - enable when ready
    cdpLegacyOnEvent: false, // most of the times not needed
}

/** CDP + Workflows - full CDP with HogFlow workflow automation */
export const CAPABILITIES_CDP_WORKFLOWS: PluginServerCapabilities = {
    ...CAPABILITIES_CDP,
    cdpBatchHogFlow: true,
    cdpCyclotronWorkerHogFlow: true,
}

/** Realtime Cohorts - precalculated filters and cohort membership */
export const CAPABILITIES_REALTIME_COHORTS: PluginServerCapabilities = {
    cdpPrecalculatedFilters: true,
    cdpCohortMembership: true,
}

/** Session Replay - recording ingestion */
export const CAPABILITIES_SESSION_REPLAY: PluginServerCapabilities = {
    sessionRecordingBlobIngestionV2: true,
}

/** Session Replay Overflow - overflow recording ingestion */
export const CAPABILITIES_SESSION_REPLAY_OVERFLOW: PluginServerCapabilities = {
    sessionRecordingBlobIngestionV2Overflow: true,
}

/** Recording API - decryption and serving of encrypted recordings */
export const CAPABILITIES_RECORDING_API: PluginServerCapabilities = {
    recordingApi: true,
}

/** Logs - log ingestion */
export const CAPABILITIES_LOGS: PluginServerCapabilities = {
    logsIngestion: true,
}

/** Feature Flags - evaluation scheduler for flags and experiments */
export const CAPABILITIES_FEATURE_FLAGS: PluginServerCapabilities = {
    evaluationScheduler: true,
}

/** LLM Analytics - sentiment classification scheduler */
export const CAPABILITIES_LLM_ANALYTICS: PluginServerCapabilities = {
    sentimentScheduler: true,
}

/** Ingestion Only - basic event ingestion without CDP processing */
export const CAPABILITIES_INGESTION_ONLY: PluginServerCapabilities = {
    ingestionV2Combined: true,
}

// =============================================================================
// Helper to merge capability groups
// =============================================================================

function mergeCapabilities(...groups: PluginServerCapabilities[]): PluginServerCapabilities {
    return Object.assign({}, ...groups)
}

// =============================================================================
// Main capability resolution
// =============================================================================

/** Map of capability group names to their capabilities */
const CAPABILITY_GROUP_MAP: Record<string, PluginServerCapabilities> = {
    cdp: CAPABILITIES_CDP,
    cdp_workflows: CAPABILITIES_CDP_WORKFLOWS,
    realtime_cohorts: CAPABILITIES_REALTIME_COHORTS,
    session_replay: CAPABILITIES_SESSION_REPLAY,
    recording_api: CAPABILITIES_RECORDING_API,
    logs: CAPABILITIES_LOGS,
    feature_flags: CAPABILITIES_FEATURE_FLAGS,
    llm_analytics: CAPABILITIES_LLM_ANALYTICS,
}

export function getPluginServerCapabilities(config: PluginsServerConfig): PluginServerCapabilities {
    const mode: PluginServerMode | null = config.PLUGIN_SERVER_MODE
        ? stringToPluginServerMode[config.PLUGIN_SERVER_MODE]
        : null

    switch (mode) {
        // Local development modes - composable groups
        case null:
            // Check if specific capability groups are requested via env var
            if (config.NODEJS_CAPABILITY_GROUPS && config.NODEJS_CAPABILITY_GROUPS.trim()) {
                const requestedGroups = config.NODEJS_CAPABILITY_GROUPS.split(',').map((g) => g.trim())
                const capabilities: PluginServerCapabilities[] = []

                for (const group of requestedGroups) {
                    const groupCapabilities = CAPABILITY_GROUP_MAP[group]
                    if (groupCapabilities) {
                        capabilities.push(groupCapabilities)
                    } else {
                        console.warn(`Unknown Node.js capability group: ${group}`)
                    }
                }

                // Add overflow config if session_replay is enabled
                if (requestedGroups.includes('session_replay')) {
                    capabilities.push({
                        sessionRecordingBlobIngestionV2Overflow: config.SESSION_RECORDING_OVERFLOW_ENABLED,
                    })
                }

                // Always include ingestion - it's required for all local dev scenarios
                return mergeCapabilities(CAPABILITIES_INGESTION_ONLY, ...capabilities)
            }

            // Default local dev: run everything for full functionality
            return mergeCapabilities(
                CAPABILITIES_INGESTION_ONLY,
                CAPABILITIES_CDP_WORKFLOWS,
                CAPABILITIES_REALTIME_COHORTS,
                CAPABILITIES_SESSION_REPLAY,
                { sessionRecordingBlobIngestionV2Overflow: config.SESSION_RECORDING_OVERFLOW_ENABLED },
                CAPABILITIES_RECORDING_API,
                CAPABILITIES_LOGS,
                CAPABILITIES_FEATURE_FLAGS,
                CAPABILITIES_LLM_ANALYTICS
            )

        case PluginServerMode.local_cdp:
            // Local CDP development: CDP + workflows + realtime cohorts
            return mergeCapabilities(
                { ingestionV2: true }, // Use ingestionV2 instead of Combined
                CAPABILITIES_CDP_WORKFLOWS,
                CAPABILITIES_REALTIME_COHORTS,
                { ingestionV2Combined: false } // Override to use ingestionV2
            )

        // Production modes - granular control for dedicated pods
        case PluginServerMode.ingestion_v2:
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
        case PluginServerMode.sentiment_scheduler:
            return {
                sentimentScheduler: true,
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
        case PluginServerMode.cdp_cyclotron_shadow_worker:
            return {
                cdpCyclotronShadowWorker: true,
            }
        case PluginServerMode.recording_api:
            return {
                recordingApi: true,
            }
    }
}
