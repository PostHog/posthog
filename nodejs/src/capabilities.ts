import { CommonConfig } from './common/config'
import { PluginServerCapabilities, PluginServerMode, stringToPluginServerMode } from './types'
import { isDevEnv } from './utils/env-utils'

// =============================================================================
// Capability Groups for Local Development
// These can be combined via hogli dev:setup to reduce event loop contention and memory overhead
// =============================================================================

/** CDP - destinations, webhooks, the events consumer, and the destination worker.
 *  Always-on baseline. Produces work to both Kafka (`cdp_cyclotron_hog`) and Postgres V2
 *  (`hogflow`) so the workflows group does not need its own events consumer. */
export const CAPABILITIES_CDP: PluginServerCapabilities = {
    cdpProcessedEvents: true,
    cdpInternalEvents: true,
    cdpCyclotronWorker: true,
    cdpApi: true,
    cdpRerunWorker: true,
    appManagementSingleton: true,
}

/** CDP Workflows - HogFlow worker and supporting services only.
 *  No events consumer here on purpose: the CDP group's events consumer already
 *  produces invocations into the Postgres V2 queue that this group drains. */
export const CAPABILITIES_CDP_WORKFLOWS: PluginServerCapabilities = {
    cdpCyclotronWorkerHogFlow: true,
    cdpBatchHogFlow: true,
    cdpCyclotronV2Janitor: isDevEnv(),
    cdpHogflowScheduler: isDevEnv(),
}

/** Realtime Cohorts - precalculated filters and cohort membership */
export const CAPABILITIES_REALTIME_COHORTS: PluginServerCapabilities = {
    cdpPrecalculatedFilters: true,
    cdpCohortMembership: true,
}

/** Optional - opt-in extras that don't belong to the always-on groups.
 *  Data-warehouse and person-updates event consumers, the legacy onEvent plugin path,
 *  and the legacy postgres-v1 HogFlow drain (being phased out). */
export const CAPABILITIES_OPTIONAL: PluginServerCapabilities = {
    cdpDataWarehouseEvents: true,
    cdpPersonUpdates: true,
    cdpLegacyOnEvent: true,
    cdpCyclotronWorkerHogFlowLegacyPg: true,
}

/** Feature Flags - evaluation scheduler for flags and experiments.
 *  Kept as a standalone single-capability group so the flags / experiments dev
 *  presets don't drag in the rest of the optional bundle. */
export const CAPABILITIES_FEATURE_FLAGS: PluginServerCapabilities = {
    evaluationScheduler: true,
}

/** Error Tracking - exception event ingestion */
export const CAPABILITIES_ERROR_TRACKING: PluginServerCapabilities = {
    errorTrackingIngestion: true,
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
    optional: CAPABILITIES_OPTIONAL,
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

            // Default local dev (single-process): run everything except ingestion, recordings,
            // logs, and traces (they run in separate processes). The mprocs split-mode wires
            // each of these groups into its own Node process via NODEJS_CAPABILITY_GROUPS.
            return mergeCapabilities(
                CAPABILITIES_CDP,
                CAPABILITIES_CDP_WORKFLOWS,
                CAPABILITIES_REALTIME_COHORTS,
                CAPABILITIES_OPTIONAL,
                CAPABILITIES_FEATURE_FLAGS,
                CAPABILITIES_ERROR_TRACKING
            )

        case PluginServerMode.local_cdp:
            // Local CDP development: CDP + workflows + realtime cohorts (ingestion runs separately)
            return mergeCapabilities(CAPABILITIES_CDP, CAPABILITIES_CDP_WORKFLOWS, CAPABILITIES_REALTIME_COHORTS)

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
        case PluginServerMode.cdp_cyclotron_worker_hogflow_legacy_pg:
            return {
                cdpCyclotronWorkerHogFlowLegacyPg: true,
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
        case PluginServerMode.ingestion_metrics:
        case PluginServerMode.ingestion_traces:
            throw new Error(`Mode ${mode} is handled by a dedicated server, not PluginServer`)
        case PluginServerMode.ingestion_error_tracking:
            return {
                errorTrackingIngestion: true,
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
        case PluginServerMode.cdp_rerun_worker:
            return {
                cdpRerunWorker: true,
            }
        case PluginServerMode.ingestion_v2:
        case PluginServerMode.ingestion_v2_testing:
        case PluginServerMode.ingestion_v2_combined:
            throw new Error(`Mode ${mode} is handled by IngestionGeneralServer, not PluginServer`)
        case PluginServerMode.ingestion_api:
            throw new Error(`Mode ${mode} is handled by IngestionApiServer, not PluginServer`)
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
