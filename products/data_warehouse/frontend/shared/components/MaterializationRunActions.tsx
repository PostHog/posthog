import { useActions, useValues } from 'kea'

import { IconEllipsis, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import {
    FULL_REFRESH_CONFIRMATION,
    REVERT_MATERIALIZATION_CONFIRMATION,
    deleteViewConfirmation,
    materializationRunActionState,
} from './materializationRunActionState'

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

    const {
        running,
        suspended,
        deleteLabel,
        accessReason,
        deleteReason,
        materializeReason,
        busyReason,
        draftError,
        noScheduleReason,
        cancelReason,
        pauseReason,
        revertReason,
        materializeCadence,
        materializeIncremental,
    } = materializationRunActionState({
        savedQuery,
        kind,
        latestJobStatus: dataModelingJobs?.results?.[0]?.status,
        jobsLoaded: !!dataModelingJobs,
        jobsError: dataModelingJobsError,
        deletingView,
        startingMaterialization,
        materializationRefreshPending,
        updatingDataWarehouseSavedQuery,
        materializationActionLoading,
        initialSyncFrequency,
        incrementalDraft,
        incrementalDraftTouched,
    })
    const deleteItem = {
        label: deleteLabel,
        'data-attr': 'node-detail-delete-view',
        status: 'danger' as const,
        disabledReason: deleteReason,
        onClick: () =>
            LemonDialog.open({
                title: deleteViewConfirmation(savedQuery).title,
                description: deleteViewConfirmation(savedQuery).description,
                primaryButton: { children: deleteLabel, status: 'danger', onClick: deleteView },
                secondaryButton: { children: 'Cancel' },
            }),
    }
    if (!savedQuery.is_materialized) {
        return (
            <>
                <LemonButton
                    type="primary"
                    size="small"
                    loading={materializationActionLoading || materializationRefreshPending || deletingView}
                    disabledReason={materializeReason}
                    data-attr="node-detail-materialize"
                    onClick={() =>
                        materializeDataWarehouseSavedQuery(viewId, materializeCadence, materializeIncremental)
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
    if (kind !== 'endpoint' && (hasMaterializationChanges || savingMaterialization)) {
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
                                      disabledReason: cancelReason,
                                  },
                              ]
                            : []),
                        ...(kind !== 'endpoint'
                            ? [
                                  ...(savedQuery.incremental?.enabled
                                      ? [
                                            {
                                                label: 'Run full refresh',
                                                disabledReason: accessReason || busyReason,
                                                onClick: () =>
                                                    LemonDialog.open({
                                                        title: FULL_REFRESH_CONFIRMATION.title,
                                                        description: FULL_REFRESH_CONFIRMATION.description,
                                                        primaryButton: {
                                                            children: FULL_REFRESH_CONFIRMATION.confirmLabel,
                                                            onClick: () => run(true),
                                                        },
                                                        secondaryButton: { children: 'Cancel' },
                                                    }),
                                            },
                                        ]
                                      : []),
                                  {
                                      label: 'Pause refreshes',
                                      disabledReason: pauseReason,
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
                                      disabledReason: revertReason,
                                      onClick: () =>
                                          LemonDialog.open({
                                              title: REVERT_MATERIALIZATION_CONFIRMATION.title,
                                              description: REVERT_MATERIALIZATION_CONFIRMATION.description,
                                              primaryButton: {
                                                  children: REVERT_MATERIALIZATION_CONFIRMATION.confirmLabel,
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
