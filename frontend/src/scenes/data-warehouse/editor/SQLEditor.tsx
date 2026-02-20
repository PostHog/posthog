import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconBook, IconChevronDown, IconDownload } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { DatabaseTree } from '~/layout/panel-layout/DatabaseTree/DatabaseTree'
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

import { ViewLinkModal } from '../ViewLinkModal'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryWindow } from './QueryWindow'
import { editorSizingLogic } from './editorSizingLogic'
import { outputPaneLogic } from './outputPaneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

interface SQLEditorProps {
    tabId?: string
    mode?: SQLEditorMode
    showDatabaseTree?: boolean
}

export function SQLEditor({ tabId, mode = SQLEditorMode.FullScene, showDatabaseTree }: SQLEditorProps): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)
    const sidebarRef = useRef(null)
    const databaseTreeRef = useRef(null)

    const shouldShowDatabaseTree = showDatabaseTree ?? true

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

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataLogicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: dataLogicKey,
        editMode: true,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: (setter) => setSourceQuery(setter(sourceQuery)),
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
        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                    <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                        <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                            <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                                <BindLogic logic={outputPaneLogic} props={{ tabId }}>
                                    <BindLogic logic={sqlEditorLogic} props={{ tabId, mode, monaco, editor }}>
                                        <VariablesQuerySync />
                                        <div className="flex h-full min-h-0 flex-col overflow-hidden">
                                            <SQLEditorSceneTitle />
                                            <div className="flex min-h-0 flex-1">
                                                {shouldShowDatabaseTree && (
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
                                                        onSetMonacoAndEditor={(nextMonaco, nextEditor) =>
                                                            setMonacoAndEditor([nextMonaco, nextEditor])
                                                        }
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                        {!mode || mode === SQLEditorMode.FullScene ? <ViewLinkModal /> : null}
                                    </BindLogic>
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
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
    } = useValues(sqlEditorLogic)
    const { updateView, updateInsight, saveAsInsight, saveAsView, saveAsEndpoint, openHistoryModal } =
        useActions(sqlEditorLogic)
    const { response } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

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
            })),
        [saveAsEndpoint, saveAsInsight, saveAsMenuItems.secondary, saveAsView]
    )

    const onPrimarySaveClick = (): void => {
        if (saveAsMenuItems.primary.action === 'endpoint') {
            saveAsEndpoint()
            return
        }

        saveAsInsight()
    }

    const [editingViewDisabledReason, EditingViewButtonIcon] = useMemo(() => {
        if (updatingDataWarehouseSavedQuery) {
            return ['Saving...', Spinner]
        }

        if (!response) {
            return ['Run query to update', IconDownload]
        }

        if (!changesToSave) {
            return ['No changes to save', IconDownload]
        }

        return [undefined, IconDownload]
    }, [updatingDataWarehouseSavedQuery, changesToSave, response])

    if (isEmbeddedMode) {
        return null
    }

    const isMaterializedView = editingView?.is_materialized === true

    return (
        <>
            <SceneTitleSection
                className="p-1 pl-3 pr-2"
                noBorder
                noPadding
                {...titleSectionProps}
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
                                                            onClick: () => saveAsInsight(),
                                                        },
                                                        {
                                                            label: 'Save as new view...',
                                                            onClick: () => saveAsView(),
                                                        },
                                                        {
                                                            label: 'Save as endpoint...',
                                                            onClick: () => saveAsEndpoint(),
                                                        },
                                                    ]}
                                                />
                                            ),
                                        },
                                    }}
                                >
                                    {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                </LemonButton>
                            </>
                        ) : editingInsight ? (
                            <LemonButton
                                disabledReason={!updateInsightButtonEnabled ? 'No updates to save' : undefined}
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
                                                        onClick: () => saveAsInsight(),
                                                    },
                                                    {
                                                        label: 'Save as new view...',
                                                        onClick: () => saveAsView(),
                                                    },
                                                    {
                                                        label: 'Save as endpoint...',
                                                        onClick: () => saveAsEndpoint(),
                                                    },
                                                ]}
                                            />
                                        ),
                                    },
                                }}
                            >
                                Update insight
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={onPrimarySaveClick}
                                sideAction={{
                                    icon: <IconChevronDown />,
                                    'data-attr': 'sql-editor-save-options-button',
                                    dropdown: {
                                        placement: 'bottom-end',
                                        overlay: <LemonMenuOverlay items={secondarySaveMenuItems} />,
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
