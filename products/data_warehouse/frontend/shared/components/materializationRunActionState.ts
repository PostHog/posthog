import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import type { IncrementalConfigDraft } from 'scenes/data-warehouse/editor/IncrementalConfigFields'
import {
    defaultCadenceWithin,
    modeDisabledReason,
    unsatisfiableReason,
} from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DataModelingSyncInterval,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryIncremental,
} from '~/types'

import { SERVING_ENGINE } from 'products/data_modeling/frontend/suspension'
import { viewEngine } from 'products/data_warehouse/frontend/shared/viewEngine'

export interface MaterializationRunActionInputs {
    savedQuery: DataWarehouseSavedQuery
    kind: 'view' | 'endpoint'
    latestJobStatus: string | null | undefined
    jobsLoaded: boolean
    jobsError: boolean
    deletingView: boolean
    startingMaterialization: boolean
    materializationRefreshPending: boolean
    updatingDataWarehouseSavedQuery: boolean
    materializationActionLoading: boolean
    initialSyncFrequency: DataModelingSyncInterval
    incrementalDraft: IncrementalConfigDraft
    incrementalDraftTouched: boolean
}

export interface MaterializationRunActionState {
    running: boolean
    suspended: boolean
    deleteLabel: string
    accessReason: string | undefined
    refreshReason: string | undefined
    deleteReason: string | undefined
    materializeReason: string | undefined
    busyReason: string | undefined
    draftError: string | undefined
    noScheduleReason: string | undefined
    cancelReason: string | undefined
    pauseReason: string | undefined
    revertReason: string | undefined
    materializeCadence: DataModelingSyncInterval
    materializeIncremental: DataWarehouseSavedQueryIncremental | null | undefined
}

export const FULL_REFRESH_CONFIRMATION = {
    title: 'Run a full refresh?',
    description:
        'This run queries all your data and rebuilds the whole table. Later runs continue using incremental mode.',
    confirmLabel: 'Run full refresh',
}

export const REVERT_MATERIALIZATION_CONFIRMATION = {
    title: 'Revert materialization',
    description:
        'This stops future materializations and removes the materialized table. The saved query remains available as a view.',
    confirmLabel: 'Revert materialization',
}

export function deleteViewConfirmation(savedQuery: DataWarehouseSavedQuery): {
    title: string
    description: string
    confirmLabel: string
} {
    const deleteLabel = savedQuery.is_materialized ? 'Delete materialized view' : 'Delete view'
    return {
        title: `${deleteLabel} "${savedQuery.name}"?`,
        description: savedQuery.is_materialized
            ? 'This deletes the saved view and its materialized data and stops scheduled refreshes. Queries that use this view will stop working. This cannot be undone.'
            : 'Queries that use this view will stop working. This cannot be undone.',
        confirmLabel: deleteLabel,
    }
}

function incrementalDraftError(draft: IncrementalConfigDraft): string | undefined {
    return draft.enabled && (!draft.incrementalKey || !draft.uniqueKey.length)
        ? 'Select the incremental column and unique key columns'
        : undefined
}

export function materializationRunActionState({
    savedQuery,
    kind,
    latestJobStatus,
    jobsLoaded,
    jobsError,
    deletingView,
    startingMaterialization,
    materializationRefreshPending,
    updatingDataWarehouseSavedQuery,
    materializationActionLoading,
    initialSyncFrequency,
    incrementalDraft,
    incrementalDraftTouched,
}: MaterializationRunActionInputs): MaterializationRunActionState {
    const running = latestJobStatus === 'Running'
    const accessReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.WarehouseObjects,
            AccessControlLevel.Editor,
            savedQuery.user_access_level
        ) ?? undefined
    const refreshReason = materializationRefreshPending ? 'Refreshing materialization status' : undefined
    const deletingReason = deletingView ? 'Deleting view' : undefined
    // The saved query and the runs load independently, so the saved query can arrive first and
    // `running` then reads false because the run list is still empty, not because nothing runs.
    // Deleting through that window leaves a run writing to a view that is gone. A run started in that
    // window has no earlier job to compare against, so it stops waiting on the first job it sees. A
    // failed request re-enables the actions rather than stranding the user, since nothing else
    // retries it on mount.
    const runStateReason = !jobsLoaded && !jobsError ? 'Checking for a running refresh' : undefined
    // Another product owns these views, so the `kind` prop cannot decide on its own: the SQL editor
    // renders this component without it, and an endpoint-origin view then looks like a plain one.
    // The saved query names its owner, and deleting through it either fails or breaks that product.
    const ownerReason = savedQuery.managed_viewset_kind
        ? 'PostHog manages this view. Turn the managed viewset off to delete it.'
        : savedQuery.origin === DataWarehouseSavedQueryOrigin.ENDPOINT
          ? 'This view belongs to an endpoint. Delete the endpoint instead.'
          : undefined
    const draftError = incrementalDraftError(incrementalDraft)
    const busyReason =
        refreshReason ||
        deletingReason ||
        runStateReason ||
        (updatingDataWarehouseSavedQuery
            ? 'Saving materialization settings'
            : materializationActionLoading
              ? 'Updating materialization'
              : running
                ? 'Materialization is currently running'
                : startingMaterialization
                  ? 'Materialization is starting'
                  : undefined)
    // Only ClickHouse serves queries, so a marker on a shadow engine means the comparison run
    // stopped, not that this model stopped refreshing.
    const suspended = !!savedQuery.suspended?.[SERVING_ENGINE]
    const cadenceReason = modeDisabledReason(savedQuery.sync_frequency_bounds) ?? undefined
    const paused = !savedQuery.sync_frequency || savedQuery.sync_frequency === 'never'

    return {
        running,
        suspended,
        deleteLabel: deleteViewConfirmation(savedQuery).confirmLabel,
        accessReason,
        refreshReason,
        deleteReason:
            accessReason ||
            ownerReason ||
            refreshReason ||
            deletingReason ||
            runStateReason ||
            (running || startingMaterialization ? 'Materialization is currently running' : undefined) ||
            (updatingDataWarehouseSavedQuery || materializationActionLoading ? 'Updating materialization' : undefined),
        materializeReason:
            accessReason ||
            viewEngine(savedQuery).capabilities.materialize.reason ||
            refreshReason ||
            deletingReason ||
            (updatingDataWarehouseSavedQuery ? 'Saving materialization settings' : undefined) ||
            // Modes with a reason cannot be materialized at all: the endpoint refuses a
            // managed viewset, and a view with no node has nothing to schedule through.
            cadenceReason ||
            unsatisfiableReason(savedQuery.sync_frequency_bounds) ||
            draftError,
        busyReason,
        draftError,
        // Resuming clears the suspension that repeated failures set, and it schedules nothing. A model
        // with no cadence has no scheduled run to go back into, so the action would promise one that
        // cannot fire. Modes with a `cadenceReason` are left alone because their cadence is not the
        // user's to pick. Sync now still clears the suspension, so this is not a dead end.
        noScheduleReason:
            paused && !cadenceReason ? 'Scheduled refreshes are paused. Pick a cadence first, then resume.' : undefined,
        cancelReason:
            accessReason ||
            refreshReason ||
            (updatingDataWarehouseSavedQuery
                ? 'Saving materialization settings'
                : materializationActionLoading
                  ? 'Canceling run'
                  : undefined),
        pauseReason:
            accessReason ||
            cadenceReason ||
            (updatingDataWarehouseSavedQuery
                ? 'Saving schedule'
                : paused
                  ? 'Already paused. Pick a cadence to resume.'
                  : undefined),
        revertReason:
            accessReason || busyReason || (updatingDataWarehouseSavedQuery ? 'Updating materialization' : undefined),
        materializeCadence: defaultCadenceWithin(savedQuery.sync_frequency_bounds, initialSyncFrequency),
        materializeIncremental:
            !incrementalDraftTouched || kind === 'endpoint'
                ? undefined
                : incrementalDraft.enabled && incrementalDraft.incrementalKey
                  ? {
                        enabled: true,
                        incremental_key: incrementalDraft.incrementalKey,
                        unique_key: incrementalDraft.uniqueKey,
                        lookback_seconds: incrementalDraft.lookbackSeconds,
                    }
                  : null,
    }
}
