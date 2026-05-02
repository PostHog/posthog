import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconBook, IconChevronDown, IconDownload, IconX } from '@posthog/icons'
import { LemonModal, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { DatabaseTree } from '~/layout/panel-layout/DatabaseTree/DatabaseTree'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import {
    VariablesLogicProps,
    variablesLogic,
} from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import {
    DataVisualizationLogicProps,
    dataVisualizationLogic,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { applyDataVisualizationQueryUpdate } from '~/queries/nodes/DataVisualization/queryUpdateUtils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { ViewLinkModal } from '../ViewLinkModal'
import { editorSizingLogic } from './editorSizingLogic'
import { QueryInfo } from './output-pane-tabs/QueryInfo'
import { OutputPane } from './OutputPane'
import { outputPaneLogic } from './outputPaneLogic'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryWindow } from './QueryWindow'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

export enum SQLEditorPanel {
    Full = 'full',
    Query = 'query',
    Output = 'output',
}

interface SQLEditorProps {
    tabId?: string
    mode?: SQLEditorMode
    showDatabaseTree?: boolean
    defaultShowDatabaseTree?: boolean
    panel?: SQLEditorPanel
    showOutputToolbar?: boolean
}

export function SQLEditor({
    tabId,
    mode = SQLEditorMode.FullScene,
    showDatabaseTree,
    defaultShowDatabaseTree = true,
    panel = SQLEditorPanel.Full,
    showOutputToolbar = true,
}: SQLEditorProps): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)
    const sidebarRef = useRef(null)
    const databaseTreeRef = useRef(null)
    const [hasShownDatabaseTree, setHasShownDatabaseTree] = useState(defaultShowDatabaseTree)

    const shouldShowDatabaseTree = showDatabaseTree ?? hasShownDatabaseTree
    const showQueryPanel = panel !== SQLEditorPanel.Output
    const showOutputPanel = panel !== SQLEditorPanel.Query
    const showSceneTitle = panel === SQLEditorPanel.Full
    const showDatabaseTreePanel = showQueryPanel && shouldShowDatabaseTree

    const editorSizingLogicProps = useMemo(
        () => ({
            editorSceneRef: ref,
            navigatorRef,
            sidebarRef,
            databaseTreeRef,
            sourceNavigatorResizerProps: {
                containerRef: navigatorRef,
                logicKey: 'source-navigator',
                placement: 'right' as const,
            },
            sidebarResizerProps: {
                containerRef: sidebarRef,
                logicKey: 'sidebar-resizer',
                placement: 'right' as const,
            },
            queryPaneResizerProps: {
                containerRef: queryPaneRef,
                logicKey: 'query-pane',
                placement: 'bottom' as const,
            },
            databaseTreeResizerProps: {
                containerRef: databaseTreeRef,
                logicKey: 'database-tree',
                placement: 'right' as const,
                persistent: true,
                marginTop: mode === SQLEditorMode.FullScene ? 8 : 0,
            },
        }),
        [mode]
    )

    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []

    useOnMountEffect(() => {
        return () => {
            setMonacoAndEditor(null)
        }
    })

    const logic = sqlEditorLogic({
        tabId: tabId || '',
        mode,
        monaco,
        editor,
    })

    const { sourceQuery, dataLogicKey } = useValues(logic)
    const { setSourceQuery } = useActions(logic)
    const sourceQueryRef = useRef(sourceQuery)
    sourceQueryRef.current = sourceQuery

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataLogicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: dataLogicKey,
        editMode: true,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: (setter) => applyDataVisualizationQueryUpdate(sourceQueryRef, setter, setSourceQuery),
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: sourceQuery.source,
        key: dataLogicKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: dataLogicKey,
        variablesOverride: undefined,
        autoLoad: false,
        onError: (error) => {
            const mountedLogic = sqlEditorLogic.findMounted({
                tabId: tabId || '',
                mode,
                monaco,
                editor,
            })

            if (mountedLogic) {
                mountedLogic.actions.setDataError(error)
            }
        },
    }

    const { loadData } = useActions(dataNodeLogic(dataNodeLogicProps))

    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), logic)

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
        sourceQuery,
        setQuery: setSourceQuery,
        onUpdate: (query) => {
            loadData('force_async', undefined, query.source)
        },
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <BindLogic logic={outputPaneLogic} props={{ tabId }}>
                                <BindLogic logic={sqlEditorLogic} props={{ tabId, mode, monaco, editor }}>
                                    <VariablesQuerySync />
                                    {panel === SQLEditorPanel.Output ? (
                                        <div className="flex h-full min-h-0 flex-col overflow-hidden">
                                            <OutputPane tabId={tabId || ''} showToolbar={showOutputToolbar} />
                                        </div>
                                    ) : (
                                        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
                                            <div className="flex h-full min-h-0 flex-col overflow-hidden">
                                                {showSceneTitle ? <SQLEditorSceneTitle /> : null}
                                                <div className="flex min-h-0 flex-1">
                                                    {showDatabaseTreePanel && (
                                                        <DatabaseTree databaseTreeRef={databaseTreeRef} />
                                                    )}
                                                    <div
                                                        data-attr="editor-scene"
                                                        className="EditorScene flex min-h-0 grow flex-row overflow-hidden"
                                                        ref={ref}
                                                    >
                                                        <QueryWindow
                                                            mode={mode}
                                                            tabId={tabId || ''}
                                                            showDatabaseTree={showDatabaseTreePanel}
                                                            onShowDatabaseTree={() => setHasShownDatabaseTree(true)}
                                                            showQueryPanel={showQueryPanel}
                                                            showOutputPanel={showOutputPanel}
                                                            onSetMonacoAndEditor={(nextMonaco, nextEditor) =>
                                                                setMonacoAndEditor([nextMonaco, nextEditor])
                                                            }
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        </BindLogic>
                                    )}
                                    <MaterializationModal tabId={tabId || ''} />
                                    {!mode || mode === SQLEditorMode.FullScene ? <ViewLinkModal /> : null}
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function MaterializationModal({ tabId }: { tabId: string }): JSX.Element {
    const { materializationModalOpen, materializationModalView, viewLoading } = useValues(sqlEditorLogic)
    const { closeMaterializationModal } = useActions(sqlEditorLogic)

    return (
        <LemonModal
            title={materializationModalView ? `Materialize ${materializationModalView.name}` : 'Materialize view'}
            isOpen={materializationModalOpen}
            onClose={closeMaterializationModal}
            width={960}
        >
            <div className="max-h-[75vh] overflow-auto">
                {viewLoading ? (
                    <div className="flex min-h-64 items-center justify-center">
                        <Spinner className="text-2xl" />
                    </div>
                ) : materializationModalView ? (
                    <QueryInfo tabId={tabId} view={materializationModalView} />
                ) : (
                    <div className="flex min-h-64 items-center justify-center">
                        <Spinner className="text-2xl" />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}

function SQLEditorSceneTitle(): JSX.Element | null {
    const {
        queryInput,
        editingView,
        editingInsight,
        insightLoading,
        sourceQuery,
        changesToSave,
        inProgressViewEdits,
        isEmbeddedMode,
        titleSectionProps,
        updateInsightButtonEnabled,
        saveAsMenuItems,
        isSourceQueryLastRun,
        isMultiQuery,
        featureFlags,
    } = useValues(sqlEditorLogic)
    const {
        updateView,
        updateInsight,
        closeEditingObject,
        saveAsInsight,
        saveAsView,
        saveAsEndpoint,
        openHistoryModal,
        setSuggestedQueryInput,
        reportAIQueryPromptOpen,
    } = useActions(sqlEditorLogic)
    const { response, responseError, responseLoading } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    const saveAsViewAccessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )

    const secondarySaveMenuItems = useMemo(
        () =>
            saveAsMenuItems.secondary.map((item) => ({
                ...item,
                onClick: () => {
                    if (item.action === 'insight') {
                        saveAsInsight()
                        return
                    }

                    if (item.action === 'endpoint') {
                        saveAsEndpoint()
                        return
                    }

                    saveAsView()
                },
                accessDisabledReason: item.action === 'view' ? saveAsViewAccessDisabledReason : undefined,
            })),
        [saveAsEndpoint, saveAsInsight, saveAsMenuItems.secondary, saveAsView, saveAsViewAccessDisabledReason]
    )

    const onPrimarySaveClick = (): void => {
        if (saveAsMenuItems.primary.action === 'endpoint') {
            saveAsEndpoint()
            return
        }

        saveAsInsight()
    }

    const saveAsDisabledReason = useMemo(() => {
        if (insightLoading) {
            return 'Loading insight...'
        }

        if (!isSourceQueryLastRun) {
            return 'Run latest query changes before saving'
        }

        if (responseLoading) {
            return 'Running query...'
        }

        if (responseError || !response) {
            return 'Run query successfully before saving'
        }

        return undefined
    }, [insightLoading, isSourceQueryLastRun, responseLoading, responseError, response])

    const [editingViewDisabledReason, EditingViewButtonIcon] = useMemo(() => {
        if (updatingDataWarehouseSavedQuery) {
            return ['Saving...', Spinner]
        }

        if (isMultiQuery) {
            return ['Views must be a single query — remove extra statements to update', IconDownload]
        }

        if (!response) {
            return ['Run query to update', IconDownload]
        }

        if (!changesToSave) {
            return ['No changes to save', IconDownload]
        }

        return [undefined, IconDownload]
    }, [updatingDataWarehouseSavedQuery, changesToSave, response, isMultiQuery])

    if (isEmbeddedMode) {
        return null
    }

    const isMaterializedView = editingView?.is_materialized === true
    const closeObjectTooltip = editingInsight
        ? 'Close this insight and reset the SQL editor to an unsaved query without clearing your SQL or visualization settings.'
        : editingView
          ? 'Close this view and reset the SQL editor to an unsaved query without clearing your SQL or visualization settings.'
          : 'Reset the SQL editor to an unsaved query without clearing your SQL or visualization settings.'

    return (
        <>
            <SceneTitleSection
                className="p-1 pl-3 pr-2"
                noBorder
                noPadding
                {...titleSectionProps}
                maxToolProps={{
                    identifier: 'execute_sql',
                    context: {
                        current_query: queryInput,
                    },
                    contextDescription: {
                        text: 'Current query',
                        icon: iconForType('sql_editor'),
                    },
                    callback: (toolOutput: string) => {
                        setSuggestedQueryInput(toolOutput, 'max_ai')
                    },
                    suggestions: [],
                    onMaxOpen: () => {
                        reportAIQueryPromptOpen()
                    },
                    introOverride: {
                        headline: 'What data do you want to analyze?',
                        description: 'Let me help you quickly write SQL, and tweak it.',
                    },
                }}
                actions={
                    <div className="flex items-center gap-2">
                        {editingView ? (
                            <>
                                <LemonButton
                                    onClick={() => openHistoryModal()}
                                    icon={<IconBook />}
                                    type="secondary"
                                    size="small"
                                >
                                    History
                                </LemonButton>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.WarehouseObjects}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={editingView.user_access_level}
                                >
                                    <LemonButton
                                        onClick={() =>
                                            updateView({
                                                id: editingView.id,
                                                query: {
                                                    ...sourceQuery.source,
                                                    query: queryInput ?? '',
                                                },
                                                types: response && 'types' in response ? (response?.types ?? []) : [],
                                                shouldRematerialize: isMaterializedView,
                                                edited_history_id: inProgressViewEdits[editingView.id],
                                            })
                                        }
                                        disabledReason={editingViewDisabledReason}
                                        icon={<EditingViewButtonIcon />}
                                        type="primary"
                                        size="small"
                                        sideAction={{
                                            icon: <IconChevronDown />,
                                            dropdown: {
                                                placement: 'bottom-end',
                                                overlay: (
                                                    <LemonMenuOverlay
                                                        items={[
                                                            {
                                                                label: 'Save as new insight...',
                                                                disabledReason: saveAsDisabledReason,
                                                                onClick: () => saveAsInsight(),
                                                            },
                                                            {
                                                                label: 'Save as new view...',
                                                                disabledReason:
                                                                    saveAsDisabledReason ??
                                                                    saveAsViewAccessDisabledReason,
                                                                onClick: () => saveAsView(),
                                                            },
                                                            ...(featureFlags[FEATURE_FLAGS.ENDPOINTS]
                                                                ? [
                                                                      {
                                                                          label: 'Save as endpoint...',
                                                                          disabledReason: saveAsDisabledReason,
                                                                          onClick: () => saveAsEndpoint(),
                                                                      },
                                                                  ]
                                                                : []),
                                                        ]}
                                                    />
                                                ),
                                            },
                                        }}
                                    >
                                        {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                    </LemonButton>
                                </AccessControlAction>
                                <LemonButton
                                    onClick={() => closeEditingObject()}
                                    icon={<IconX />}
                                    type="tertiary"
                                    size="small"
                                    aria-label="close"
                                    tooltip={closeObjectTooltip}
                                />
                            </>
                        ) : editingInsight ? (
                            <>
                                <LemonButton
                                    disabledReason={
                                        !isSourceQueryLastRun
                                            ? 'Run latest query changes before saving'
                                            : !updateInsightButtonEnabled
                                              ? 'No updates to save'
                                              : undefined
                                    }
                                    loading={insightLoading}
                                    type="primary"
                                    size="small"
                                    onClick={() => updateInsight()}
                                    sideAction={{
                                        icon: <IconChevronDown />,
                                        dropdown: {
                                            placement: 'bottom-end',
                                            overlay: (
                                                <LemonMenuOverlay
                                                    items={[
                                                        {
                                                            label: 'Save as new insight...',
                                                            disabledReason: saveAsDisabledReason,
                                                            onClick: () => saveAsInsight(),
                                                        },
                                                        {
                                                            label: 'Save as new view...',
                                                            disabledReason:
                                                                saveAsDisabledReason ?? saveAsViewAccessDisabledReason,
                                                            onClick: () => saveAsView(),
                                                        },
                                                        ...(featureFlags[FEATURE_FLAGS.ENDPOINTS]
                                                            ? [
                                                                  {
                                                                      label: 'Save as endpoint...',
                                                                      disabledReason: saveAsDisabledReason,
                                                                      onClick: () => saveAsEndpoint(),
                                                                  },
                                                              ]
                                                            : []),
                                                    ]}
                                                />
                                            ),
                                        },
                                    }}
                                >
                                    Update insight
                                </LemonButton>
                                <LemonButton
                                    onClick={() => closeEditingObject()}
                                    icon={<IconX />}
                                    type="secondary"
                                    size="small"
                                    noPadding
                                    aria-label="close"
                                    tooltip={closeObjectTooltip}
                                />
                            </>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={onPrimarySaveClick}
                                disabledReason={saveAsDisabledReason}
                                sideAction={{
                                    icon: <IconChevronDown />,
                                    'data-attr': 'sql-editor-save-options-button',
                                    dropdown: {
                                        placement: 'bottom-end',
                                        overlay: (
                                            <LemonMenuOverlay
                                                items={secondarySaveMenuItems.map((item) => ({
                                                    ...item,
                                                    disabledReason: saveAsDisabledReason ?? item.accessDisabledReason,
                                                }))}
                                            />
                                        ),
                                    },
                                }}
                            >
                                {saveAsMenuItems.primary.label}
                            </LemonButton>
                        )}
                    </div>
                }
            />
            <QueryHistoryModal />
        </>
    )
}

function VariablesQuerySync(): null {
    const { queryInput } = useValues(sqlEditorLogic)
    const { setEditorQuery } = useActions(variablesLogic)

    useEffect(() => {
        setEditorQuery(queryInput ?? '')
    }, [queryInput, setEditorQuery])

    return null
}
