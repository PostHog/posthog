import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCheck, IconExternal, IconPause, IconPlay, IconRefresh, IconTrash, IconUndo, IconX } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { nodeEndpointUrl } from 'products/data_modeling/frontend/endpointModelName'
import {
    FULL_REFRESH_CONFIRMATION,
    REVERT_MATERIALIZATION_CONFIRMATION,
    deleteViewConfirmation,
    materializationRunActionState,
} from 'products/data_warehouse/frontend/shared/components/materializationRunActionState'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const RESOURCE_TYPE = 'node-detail'

/** The first of these the list holds carries the title row, which keeps the original buttons with their loading states. */
const TITLE_ACTION_IDS = [
    `${RESOURCE_TYPE}-menubar-update-view`,
    `${RESOURCE_TYPE}-menubar-retry-status-refresh`,
    `${RESOURCE_TYPE}-menubar-materialize`,
    `${RESOURCE_TYPE}-menubar-save-materialization`,
    `${RESOURCE_TYPE}-menubar-sync-now`,
    `${RESOURCE_TYPE}-menubar-open-endpoint`,
]

interface NodeDetailSceneMenuBarProps {
    id: string
    titleActions: JSX.Element | undefined
}

export function NodeDetailSceneMenuBar(props: NodeDetailSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <NodeDetailSceneMenuBarInner {...props} /> : null
}

function NodeDetailSceneMenuBarInner({ id, titleActions }: NodeDetailSceneMenuBarProps): JSX.Element {
    const {
        node,
        savedQuery: initialSavedQuery,
        queryEditorState,
        effectiveTab,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { discardQueryEditorChanges, updateViewFromQueryEditor } = useActions(nodeDetailSceneLogic({ id }))
    const kind = node?.type === 'endpoint' ? 'endpoint' : 'view'
    const viewId = node?.saved_query_id ?? ''
    const jobsLogic = materializationJobsLogic({ viewId, kind })
    const {
        savedQuery: currentSavedQuery,
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
    } = useValues(jobsLogic)
    const {
        refreshMaterialization,
        deleteView,
        setStartingMaterialization,
        resumeMaterialization,
        saveMaterializationChanges,
        discardMaterializationChanges,
    } = useActions(jobsLogic)
    const { updatingDataWarehouseSavedQuery, materializationActionLoading } = useValues(dataWarehouseViewsLogic)
    const {
        runDataWarehouseSavedQuery,
        materializeDataWarehouseSavedQuery,
        cancelDataWarehouseSavedQuery,
        updateDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)
    const savedQuery = currentSavedQuery ?? initialSavedQuery

    const materializationActions = (): SceneAction[] => {
        if (!node || !savedQuery) {
            return []
        }
        if (materializationRefreshPending && (savedQueryError || dataModelingJobsError)) {
            return [
                {
                    group: 'edit',
                    section: 'materialization',
                    id: `${RESOURCE_TYPE}-menubar-retry-status-refresh`,
                    label: 'Retry status refresh',
                    icon: <IconRefresh />,
                    tooltip: "Couldn't refresh materialization status. Retry before running another action.",
                    disabledReason:
                        savedQueryLoading || dataModelingJobsLoading ? 'Refreshing materialization status' : undefined,
                    onSelect: refreshMaterialization,
                },
            ]
        }
        const state = materializationRunActionState({
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
        const deleteAction: SceneAction[] =
            kind !== 'endpoint'
                ? [
                      {
                          group: 'file',
                          section: 'delete',
                          id: `${RESOURCE_TYPE}-menubar-delete-view`,
                          label: state.deleteLabel,
                          icon: <IconTrash />,
                          destructive: true,
                          disabledReason: state.deleteReason,
                          onSelect: () =>
                              LemonDialog.open({
                                  title: deleteViewConfirmation(savedQuery).title,
                                  description: deleteViewConfirmation(savedQuery).description,
                                  primaryButton: { children: state.deleteLabel, status: 'danger', onClick: deleteView },
                                  secondaryButton: { children: 'Cancel' },
                              }),
                      },
                  ]
                : []

        if (!savedQuery.is_materialized) {
            return [
                {
                    group: 'edit',
                    section: 'materialization',
                    id: `${RESOURCE_TYPE}-menubar-materialize`,
                    label: 'Materialize',
                    icon: <IconPlay />,
                    disabledReason:
                        state.materializeReason ||
                        (materializationActionLoading || materializationRefreshPending || deletingView
                            ? 'Updating materialization'
                            : undefined),
                    onSelect: () =>
                        materializeDataWarehouseSavedQuery(
                            viewId,
                            state.materializeCadence,
                            state.materializeIncremental
                        ),
                },
                ...deleteAction,
            ]
        }
        if (kind !== 'endpoint' && (hasMaterializationChanges || savingMaterialization)) {
            return [
                {
                    group: 'edit',
                    section: 'materialization',
                    id: `${RESOURCE_TYPE}-menubar-save-materialization`,
                    label: 'Save materialization settings',
                    icon: <IconCheck />,
                    disabledReason:
                        state.accessReason ||
                        state.busyReason ||
                        state.draftError ||
                        (savingMaterialization ? 'Saving materialization settings' : undefined),
                    onSelect: saveMaterializationChanges,
                },
                {
                    group: 'edit',
                    section: 'materialization',
                    id: `${RESOURCE_TYPE}-menubar-discard-materialization`,
                    label: 'Discard materialization changes',
                    icon: <IconUndo />,
                    disabledReason: savingMaterialization ? 'Saving materialization settings' : undefined,
                    onSelect: discardMaterializationChanges,
                },
                {
                    group: 'edit',
                    section: 'materialization',
                    id: `${RESOURCE_TYPE}-menubar-sync-now`,
                    label: 'Sync now',
                    icon: <IconRefresh />,
                    disabledReason: 'Save or discard your changes first',
                    onSelect: () => {},
                },
            ]
        }
        const run = (rebuild = false): void => {
            setStartingMaterialization(true)
            runDataWarehouseSavedQuery(viewId, rebuild)
        }
        return [
            ...(state.suspended
                ? ([
                      {
                          group: 'edit',
                          section: 'materialization',
                          id: `${RESOURCE_TYPE}-menubar-resume`,
                          label: 'Resume schedule',
                          icon: <IconPlay />,
                          disabledReason:
                              state.accessReason ||
                              state.busyReason ||
                              state.noScheduleReason ||
                              (resumingMaterialization ? 'Resuming schedule' : undefined),
                          onSelect: resumeMaterialization,
                      },
                  ] satisfies SceneAction[])
                : []),
            {
                group: 'edit',
                section: 'materialization',
                id: `${RESOURCE_TYPE}-menubar-sync-now`,
                label: startingMaterialization ? 'Starting' : state.running ? 'Running' : 'Sync now',
                icon: <IconRefresh />,
                disabledReason: state.accessReason || state.busyReason,
                onSelect: () => run(),
            },
            ...(state.running
                ? ([
                      {
                          group: 'edit',
                          section: 'materialization',
                          id: `${RESOURCE_TYPE}-menubar-cancel-run`,
                          label: 'Cancel run',
                          icon: <IconX />,
                          disabledReason: state.cancelReason,
                          onSelect: () => cancelDataWarehouseSavedQuery(viewId),
                      },
                  ] satisfies SceneAction[])
                : []),
            ...(kind !== 'endpoint'
                ? ([
                      ...(savedQuery.incremental?.enabled
                          ? ([
                                {
                                    group: 'edit',
                                    section: 'materialization',
                                    id: `${RESOURCE_TYPE}-menubar-full-refresh`,
                                    label: 'Run full refresh',
                                    icon: <IconRefresh />,
                                    opensFloatingUi: true,
                                    disabledReason: state.accessReason || state.busyReason,
                                    onSelect: () =>
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
                            ] satisfies SceneAction[])
                          : []),
                      {
                          group: 'edit',
                          section: 'materialization',
                          id: `${RESOURCE_TYPE}-menubar-pause-refreshes`,
                          label: 'Pause refreshes',
                          icon: <IconPause />,
                          disabledReason: state.pauseReason,
                          onSelect: () =>
                              updateDataWarehouseSavedQuery({
                                  id: viewId,
                                  sync_frequency: 'never',
                                  types: [[]],
                                  lifecycle: 'update',
                              }),
                      },
                      {
                          group: 'file',
                          section: 'delete',
                          id: `${RESOURCE_TYPE}-menubar-revert-materialization`,
                          label: 'Revert materialization',
                          icon: <IconUndo />,
                          destructive: true,
                          disabledReason: state.revertReason,
                          onSelect: () =>
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
                  ] satisfies SceneAction[])
                : []),
            ...deleteAction,
        ]
    }

    const showQueryEditorActions =
        !!node && !!savedQuery && kind !== 'endpoint' && !!queryEditorState && effectiveTab === 'query'

    const actions: SceneAction[] = [
        ...(node && savedQuery && kind === 'endpoint'
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-open-endpoint`,
                      label: 'Open endpoint',
                      icon: <IconExternal />,
                      onSelect: () => router.actions.push(nodeEndpointUrl(node)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showQueryEditorActions && queryEditorState
            ? ([
                  {
                      group: 'edit',
                      section: 'query',
                      id: `${RESOURCE_TYPE}-menubar-update-view`,
                      label: queryEditorState.isMaterializedView ? 'Update and re-materialize view' : 'Update view',
                      icon: <IconCheck />,
                      disabledReason:
                          queryEditorState.updateDisabledReason ??
                          (queryEditorState.updateLoading ? 'Updating view' : undefined),
                      onSelect: () => updateViewFromQueryEditor(),
                  },
                  {
                      group: 'edit',
                      section: 'query',
                      id: `${RESOURCE_TYPE}-menubar-discard-query-changes`,
                      label: 'Discard query changes',
                      icon: <IconUndo />,
                      disabledReason: queryEditorState.discardDisabledReason,
                      onSelect: () => discardQueryEditorChanges(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...materializationActions(),
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <SceneActivityIndicator
                    prefix="Created"
                    at={node?.saved_query_id ? savedQuery?.created_at : node?.created_at}
                    by={savedQuery?.created_by}
                />
            ),
        },
    ]

    const titleActionId = titleActions ? TITLE_ACTION_IDS.find((id) => actions.some((a) => a.id === id)) : undefined
    const withTitle: SceneAction[] = actions.map((action) =>
        action.id === titleActionId && titleActions
            ? { ...action, pinned: { order: 1, variant: 'primary' as const, render: () => titleActions } }
            : action
    )

    return <SceneActions actions={withTitle} dataAttrKey={RESOURCE_TYPE} />
}
