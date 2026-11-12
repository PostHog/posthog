import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconRefresh } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import {
    FULL_REFRESH_CONFIRMATION,
    REVERT_MATERIALIZATION_CONFIRMATION,
    deleteViewConfirmation,
    materializationRunActionState,
} from './materializationRunActionState'
import { QuillRunActionConfirmDialog, type RunActionConfirmation } from './QuillRunActionConfirmDialog'

export function QuillMaterializationRunActions({
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
    const [confirmation, setConfirmation] = useState<RunActionConfirmation | null>(null)
    const [confirmationOpen, setConfirmationOpen] = useState(false)
    const askToConfirm = (nextConfirmation: RunActionConfirmation): void => {
        setConfirmation(nextConfirmation)
        setConfirmationOpen(true)
    }

    if (!savedQuery) {
        return null
    }

    if (materializationRefreshPending && (savedQueryError || dataModelingJobsError)) {
        return (
            <Button
                variant="outline"
                loading={savedQueryLoading || dataModelingJobsLoading}
                onClick={refreshMaterialization}
                aria-label="Retry status refresh"
                tooltip="Couldn't refresh materialization status. Retry before running another action."
            >
                Retry status refresh
            </Button>
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

    const confirmDelete = (): void =>
        askToConfirm({ ...deleteViewConfirmation(savedQuery), destructive: true, onConfirm: deleteView })
    const deleteItem = (
        <DropdownMenuItem
            variant="destructive"
            disabledReason={deleteReason}
            onClick={confirmDelete}
            data-attr="node-detail-delete-view"
        >
            {deleteLabel}
        </DropdownMenuItem>
    )
    const dialog = (
        <QuillRunActionConfirmDialog
            confirmation={confirmation}
            open={confirmationOpen}
            onClose={() => setConfirmationOpen(false)}
            onClosed={() => setConfirmation(null)}
        />
    )

    if (!savedQuery.is_materialized) {
        return (
            <>
                <Button
                    variant="primary"
                    loading={materializationActionLoading || materializationRefreshPending || deletingView}
                    disabledReason={materializeReason}
                    data-attr="node-detail-materialize"
                    onClick={() =>
                        materializeDataWarehouseSavedQuery(viewId, materializeCadence, materializeIncremental)
                    }
                >
                    Materialize
                </Button>
                {kind !== 'endpoint' && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="icon"
                                    loading={deletingView}
                                    aria-label="View actions"
                                    tooltip="View actions"
                                    data-attr="node-detail-view-actions"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">{deleteItem}</DropdownMenuContent>
                    </DropdownMenu>
                )}
                {dialog}
            </>
        )
    }

    if (kind !== 'endpoint' && (hasMaterializationChanges || savingMaterialization)) {
        return (
            <>
                <Button variant="outline" disabledReason="Save or discard your changes first">
                    <IconRefresh />
                    Sync now
                </Button>
                <Button
                    variant="outline"
                    disabledReason={savingMaterialization ? 'Saving materialization settings' : undefined}
                    onClick={discardMaterializationChanges}
                >
                    Discard changes
                </Button>
                <Button
                    variant="primary"
                    loading={savingMaterialization}
                    disabledReason={accessReason || busyReason || draftError}
                    onClick={saveMaterializationChanges}
                >
                    Save
                </Button>
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
                <Button
                    variant="outline"
                    onClick={resumeMaterialization}
                    loading={resumingMaterialization}
                    disabledReason={accessReason || busyReason || noScheduleReason}
                    data-attr="node-detail-resume"
                >
                    Resume schedule
                </Button>
            )}
            <Button
                variant="primary"
                onClick={() => run()}
                loading={startingMaterialization || running || materializationActionLoading}
                disabledReason={accessReason || busyReason}
                data-attr="node-detail-sync-now"
            >
                <IconRefresh />
                {startingMaterialization ? 'Starting…' : running ? 'Running…' : 'Sync now'}
            </Button>
            {(kind !== 'endpoint' || running) && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                loading={deletingView}
                                aria-label="Materialization actions"
                                tooltip="Materialization actions"
                                data-attr="node-detail-materialization-actions"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {running && (
                            <DropdownMenuItem
                                disabledReason={cancelReason}
                                onClick={() => cancelDataWarehouseSavedQuery(viewId)}
                            >
                                Cancel run
                            </DropdownMenuItem>
                        )}
                        {kind !== 'endpoint' && (
                            <>
                                {savedQuery.incremental?.enabled && (
                                    <DropdownMenuItem
                                        disabledReason={accessReason || busyReason}
                                        onClick={() =>
                                            askToConfirm({
                                                ...FULL_REFRESH_CONFIRMATION,
                                                destructive: false,
                                                onConfirm: () => run(true),
                                            })
                                        }
                                    >
                                        Run full refresh
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuItem
                                    disabledReason={pauseReason}
                                    onClick={() =>
                                        updateDataWarehouseSavedQuery({
                                            id: viewId,
                                            sync_frequency: 'never',
                                            types: [[]],
                                            lifecycle: 'update',
                                        })
                                    }
                                >
                                    Pause refreshes
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                    variant="destructive"
                                    disabledReason={revertReason}
                                    onClick={() =>
                                        askToConfirm({
                                            ...REVERT_MATERIALIZATION_CONFIRMATION,
                                            destructive: true,
                                            onConfirm: () => revertMaterialization(viewId),
                                        })
                                    }
                                >
                                    Revert materialization
                                </DropdownMenuItem>
                                {deleteItem}
                            </>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {dialog}
        </>
    )
}
