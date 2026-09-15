import { useActions, useValues } from 'kea'

import { IconEllipsis, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import {
    defaultCadenceWithin,
    unsatisfiableReason,
    modeDisabledReason,
} from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SERVING_ENGINE } from 'products/data_modeling/frontend/suspension'

export function MaterializationRunActions({
    viewId,
    kind = 'view',
}: {
    viewId: string
    kind?: 'view' | 'endpoint'
}): JSX.Element | null {
    const {
        savedQuery,
        deletingView,
        dataModelingJobs,
        startingMaterialization,
        resumingMaterialization,
        initialSyncFrequency,
        incrementalDraft,
        incrementalDraftTouched,
        savedQueryError,
        savedQueryLoading,
        dataModelingJobsError,
        dataModelingJobsLoading,
        hasMaterializationChanges,
        savingMaterialization,
        materializationRefreshPending,
    } = useValues(materializationJobsLogic({ viewId, kind }))
    const {
        refreshMaterialization,
        deleteView,
        setStartingMaterialization,
        resumeMaterialization,
        saveMaterializationChanges,
        discardMaterializationChanges,
    } = useActions(materializationJobsLogic({ viewId, kind }))
    const { updatingDataWarehouseSavedQuery, materializationActionLoading } = useValues(dataWarehouseViewsLogic)
    const {
        runDataWarehouseSavedQuery,
        materializeDataWarehouseSavedQuery,
        cancelDataWarehouseSavedQuery,
        updateDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!savedQuery) {
        return null
    }

    if (materializationRefreshPending && (savedQueryError || dataModelingJobsError)) {
        return (
            <LemonButton
                type="secondary"
                size="small"
                loading={savedQueryLoading || dataModelingJobsLoading}
                onClick={refreshMaterialization}
                aria-label="Retry status refresh"
                tooltip="Couldn't refresh materialization status. Retry before running another action."
            >
                Retry status refresh
            </LemonButton>
        )
    }

    const running = dataModelingJobs?.results?.[0]?.status === 'Running'
    const accessReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor,
        savedQuery.user_access_level
    )
    const refreshReason = materializationRefreshPending ? 'Refreshing materialization status' : undefined
    // Another product owns these views, so the `kind` prop cannot decide on its own: the SQL editor
    // renders this component without it, and an endpoint-origin view then looks like a plain one.
    // The saved query names its owner, and deleting through it either fails or breaks that product.
    const ownerReason = savedQuery.managed_viewset_kind
        ? 'PostHog manages this view. Turn the managed viewset off to delete it.'
        : savedQuery.origin === DataWarehouseSavedQueryOrigin.ENDPOINT
          ? 'This view belongs to an endpoint. Delete the endpoint instead.'
          : undefined
    const deleteLabel = savedQuery.is_materialized ? 'Delete materialized view' : 'Delete view'
    const deleteItem = {
        label: deleteLabel,
        'data-attr': 'node-detail-delete-view',
        status: 'danger' as const,
        disabledReason:
            accessReason ||
            ownerReason ||
            refreshReason ||
            (deletingView ? 'Deleting view' : undefined) ||
            // The saved query and the runs load independently, so the saved query can arrive first and
            // `running` then reads false because the run list is still empty, not because nothing runs.
            // Deleting through that window leaves a run writing to a view that is gone. A failed request
            // re-enables the item rather than stranding the user, since nothing else retries it on mount.
            (!dataModelingJobs && !dataModelingJobsError ? 'Checking for a running refresh' : undefined) ||
            (running || startingMaterialization ? 'Materialization is currently running' : undefined) ||
            (updatingDataWarehouseSavedQuery || materializationActionLoading ? 'Updating materialization' : undefined),
        onClick: () =>
            LemonDialog.open({
                title: `${deleteLabel} "${savedQuery.name}"?`,
                description: savedQuery.is_materialized
                    ? 'This deletes the saved view and its materialized data and stops scheduled refreshes. Queries that use this view will stop working. This cannot be undone.'
                    : 'Queries that use this view will stop working. This cannot be undone.',
                primaryButton: { children: deleteLabel, status: 'danger', onClick: deleteView },
                secondaryButton: { children: 'Cancel' },
            }),
    }
    if (!savedQuery.is_materialized) {
        const draftError =
            incrementalDraft.enabled && (!incrementalDraft.incrementalKey || !incrementalDraft.uniqueKey.length)
                ? 'Select the incremental column and unique key columns'
                : undefined
        return (
            <>
                <LemonButton
                    type="primary"
                    size="small"
                    loading={materializationActionLoading || materializationRefreshPending || deletingView}
                    disabledReason={
                        accessReason ||
                        refreshReason ||
                        (deletingView ? 'Deleting view' : undefined) ||
                        (updatingDataWarehouseSavedQuery ? 'Saving materialization settings' : undefined) ||
                        // Modes with a reason cannot be materialized at all: the endpoint refuses a
                        // managed viewset, and a view with no node has nothing to schedule through.
                        modeDisabledReason(savedQuery.sync_frequency_bounds) ||
                        unsatisfiableReason(savedQuery.sync_frequency_bounds) ||
                        draftError
                    }
                    data-attr="node-detail-materialize"
                    onClick={() =>
                        materializeDataWarehouseSavedQuery(
                            viewId,
                            defaultCadenceWithin(savedQuery.sync_frequency_bounds, initialSyncFrequency),
                            !incrementalDraftTouched ||
                                kind === 'endpoint' ||
                                !featureFlags[FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]
                                ? undefined
                                : incrementalDraft.enabled && incrementalDraft.incrementalKey
                                  ? {
                                        enabled: true,
                                        incremental_key: incrementalDraft.incrementalKey,
                                        unique_key: incrementalDraft.uniqueKey,
                                        lookback_seconds: incrementalDraft.lookbackSeconds,
                                    }
                                  : null
                        )
                    }
                >
                    Materialize
                </LemonButton>
                {kind !== 'endpoint' && (
                    <LemonMenu items={[deleteItem]}>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconEllipsis />}
                            loading={deletingView}
                            aria-label="View actions"
                            data-attr="node-detail-view-actions"
                        />
                    </LemonMenu>
                )}
            </>
        )
    }
    const busyReason =
        refreshReason ||
        (deletingView ? 'Deleting view' : undefined) ||
        (updatingDataWarehouseSavedQuery
            ? 'Saving materialization settings'
            : materializationActionLoading
              ? 'Updating materialization'
              : running
                ? 'Materialization is currently running'
                : startingMaterialization
                  ? 'Materialization is starting'
                  : undefined)
    if (kind !== 'endpoint' && (hasMaterializationChanges || savingMaterialization)) {
        const draftError =
            incrementalDraft.enabled && (!incrementalDraft.incrementalKey || !incrementalDraft.uniqueKey.length)
                ? 'Select the incremental column and unique key columns'
                : undefined
        return (
            <>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    disabledReason="Save or discard your changes first"
                >
                    Sync now
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={savingMaterialization ? 'Saving materialization settings' : undefined}
                    onClick={discardMaterializationChanges}
                >
                    Discard changes
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    loading={savingMaterialization}
                    disabledReason={accessReason || busyReason || draftError}
                    onClick={saveMaterializationChanges}
                >
                    Save
                </LemonButton>
            </>
        )
    }
    // Only ClickHouse serves queries, so a marker on a shadow engine means the comparison run
    // stopped, not that this model stopped refreshing.
    const suspended =
        !!featureFlags[FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES] && !!savedQuery.suspended?.[SERVING_ENGINE]
    const cadenceReason = modeDisabledReason(savedQuery.sync_frequency_bounds)
    const paused = !savedQuery.sync_frequency || savedQuery.sync_frequency === 'never'
    // Resuming clears the suspension that repeated failures set, and it schedules nothing. A model
    // with no cadence has no scheduled run to go back into, so the action would promise one that
    // cannot fire. Modes with a `cadenceReason` are left alone because their cadence is not the
    // user's to pick. Sync now still clears the suspension, so this is not a dead end.
    const noScheduleReason =
        paused && !cadenceReason ? 'Scheduled refreshes are paused. Pick a cadence first, then resume.' : undefined
    const run = (rebuild = false): void => {
        setStartingMaterialization(true)
        runDataWarehouseSavedQuery(viewId, rebuild)
    }

    return (
        <>
            {suspended && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={resumeMaterialization}
                    loading={resumingMaterialization}
                    disabledReason={accessReason || busyReason || noScheduleReason}
                    data-attr="node-detail-resume"
                >
                    Resume schedule
                </LemonButton>
            )}
            <LemonButton
                type="primary"
                size="small"
                icon={<IconRefresh />}
                onClick={() => run()}
                loading={startingMaterialization || running || materializationActionLoading}
                disabledReason={accessReason || busyReason}
                data-attr="node-detail-sync-now"
            >
                {startingMaterialization ? 'Starting…' : running ? 'Running…' : 'Sync now'}
            </LemonButton>
            {(kind !== 'endpoint' || running) && (
                <LemonMenu
                    items={[
                        ...(running
                            ? [
                                  {
                                      label: 'Cancel run',
                                      onClick: () => cancelDataWarehouseSavedQuery(viewId),
                                      disabledReason:
                                          accessReason ||
                                          refreshReason ||
                                          (updatingDataWarehouseSavedQuery
                                              ? 'Saving materialization settings'
                                              : materializationActionLoading
                                                ? 'Canceling run'
                                                : undefined),
                                  },
                              ]
                            : []),
                        ...(kind !== 'endpoint'
                            ? [
                                  ...(featureFlags[FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS] &&
                                  savedQuery.incremental?.enabled
                                      ? [
                                            {
                                                label: 'Run full refresh',
                                                disabledReason: accessReason || busyReason,
                                                onClick: () =>
                                                    LemonDialog.open({
                                                        title: 'Run a full refresh?',
                                                        description:
                                                            'This run queries all your data and rebuilds the whole table. Later runs continue using incremental mode.',
                                                        primaryButton: {
                                                            children: 'Run full refresh',
                                                            onClick: () => run(true),
                                                        },
                                                        secondaryButton: { children: 'Cancel' },
                                                    }),
                                            },
                                        ]
                                      : []),
                                  {
                                      label: 'Pause refreshes',
                                      disabledReason:
                                          accessReason ||
                                          cadenceReason ||
                                          (updatingDataWarehouseSavedQuery
                                              ? 'Saving schedule'
                                              : paused
                                                ? 'Already paused. Pick a cadence to resume.'
                                                : undefined),
                                      onClick: () =>
                                          updateDataWarehouseSavedQuery({
                                              id: viewId,
                                              sync_frequency: 'never',
                                              types: [[]],
                                              lifecycle: 'update',
                                          }),
                                  },
                                  {
                                      label: 'Revert materialization',
                                      status: 'danger' as const,
                                      disabledReason:
                                          accessReason ||
                                          busyReason ||
                                          (updatingDataWarehouseSavedQuery ? 'Updating materialization' : undefined),
                                      onClick: () =>
                                          LemonDialog.open({
                                              title: 'Revert materialization',
                                              description:
                                                  'This stops future materializations and removes the materialized table. The saved query remains available as a view.',
                                              primaryButton: {
                                                  children: 'Revert materialization',
                                                  status: 'danger',
                                                  onClick: () => revertMaterialization(viewId),
                                              },
                                              secondaryButton: { children: 'Cancel' },
                                          }),
                                  },
                                  deleteItem,
                              ]
                            : []),
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconEllipsis />}
                        loading={deletingView}
                        aria-label="Materialization actions"
                        data-attr="node-detail-materialization-actions"
                    />
                </LemonMenu>
            )}
        </>
    )
}
