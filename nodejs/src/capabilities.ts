import { CommonConfig } from './common/config'
import { PluginServerCapabilities, PluginServerMode, stringToPluginServerMode } from './types'
import { isDevEnv } from './utils/env-utils'

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
    cdpCyclotronV2Janitor: isDevEnv(),
    cdpHogflowScheduler: isDevEnv(),
}

/** Realtime Cohorts - precalculated filters and cohort membership */
export const CAPABILITIES_REALTIME_COHORTS: PluginServerCapabilities = {
    cdpPrecalculatedFilters: true,
    cdpCohortMembership: true,
}

/** Logs - log ingestion */
export const CAPABILITIES_LOGS: PluginServerCapabilities = {
    logsIngestion: true,
}

/** Error Tracking - exception event ingestion */
export const CAPABILITIES_ERROR_TRACKING: PluginServerCapabilities = {
    errorTrackingIngestion: true,
}

/** Traces - trace ingestion */
export const CAPABILITIES_TRACES: PluginServerCapabilities = {
    tracesIngestion: true,
}

/** Feature Flags - evaluation scheduler for flags and experiments */
export const CAPABILITIES_FEATURE_FLAGS: PluginServerCapabilities = {
    evaluationScheduler: true,
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
    logs: CAPABILITIES_LOGS,
    traces: CAPABILITIES_TRACES,
    feature_flags: CAPABILITIES_FEATURE_FLAGS,
}

export function getPluginServerCapabilities(
    config: Pick<CommonConfig, 'PLUGIN_SERVER_MODE' | 'NODEJS_CAPABILITY_GROUPS'>
): PluginServerCapabilities {
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

                return mergeCapabilities(...capabilities)
            }

            // Default local dev: run everything except ingestion and recordings (they run in separate processes)
            return mergeCapabilities(
                CAPABILITIES_CDP_WORKFLOWS,
                CAPABILITIES_REALTIME_COHORTS,
                CAPABILITIES_LOGS,
                CAPABILITIES_ERROR_TRACKING,
                CAPABILITIES_FEATURE_FLAGS
            )

        case PluginServerMode.local_cdp:
            // Local CDP development: CDP + workflows + realtime cohorts (ingestion runs separately)
            return mergeCapabilities(CAPABILITIES_CDP_WORKFLOWS, CAPABILITIES_REALTIME_COHORTS)

        // Production modes - granular control for dedicated pods
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
        case PluginServerMode.ingestion_logs:
            return {
                logsIngestion: true,
            }
        case PluginServerMode.ingestion_error_tracking:
            return {
                errorTrackingIngestion: true,
            }
        case PluginServerMode.ingestion_traces:
            return {
                tracesIngestion: true,
            }
        case PluginServerMode.cdp_batch_hogflow_requests:
            return {
                cdpBatchHogFlow: true,
            }
        case PluginServerMode.cdp_data_warehouse_events:
            return {
                cdpDataWarehouseEvents: true,
            }
        case PluginServerMode.cdp_cyclotron_v2_janitor:
            return {
                cdpCyclotronV2Janitor: true,
            }
        case PluginServerMode.ingestion_v2:
        case PluginServerMode.ingestion_v2_testing:
        case PluginServerMode.ingestion_v2_combined:
            throw new Error(`Mode ${mode} is handled by IngestionGeneralServer, not PluginServer`)
        case PluginServerMode.cdp_hogflow_scheduler:
            return {
                cdpHogflowScheduler: true,
            }
        case PluginServerMode.recordings_blob_ingestion_v2:
        case PluginServerMode.recordings_blob_ingestion_v2_overflow:
        case PluginServerMode.recording_api:
            throw new Error(`Mode ${mode} is handled by IngestionSessionReplayServer, not PluginServer`)
    }
}
