import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { useRef, useState } from 'react'

import { IconDownload } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import {
    VariablesLogicProps,
    variablesLogic,
} from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { DataVisualizationLogicProps } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'

import { ViewLinkModal } from '../ViewLinkModal'
import { QueryWindow } from './QueryWindow'
import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic } from './outputPaneLogic'

export const scene: SceneExport = {
    component: EditorScene,
    logic: multitabEditorLogic,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)
    const sidebarRef = useRef(null)

    const editorSizingLogicProps = {
        editorSceneRef: ref,
        navigatorRef,
        sidebarRef,
        sourceNavigatorResizerProps: {
            containerRef: navigatorRef,
            logicKey: 'source-navigator',
            placement: 'right',
        },
        sidebarResizerProps: {
            containerRef: sidebarRef,
            logicKey: 'sidebar-resizer',
            placement: 'right',
        },
        queryPaneResizerProps: {
            containerRef: queryPaneRef,
            logicKey: 'query-pane',
            placement: 'bottom',
        },
    }

    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const codeEditorKey = tabId || 'hogQLQueryEditor' ///${router.values.location.pathname}`

    const logic = multitabEditorLogic({
        key: codeEditorKey,
        tabId,
        monaco,
        editor,
    })

    const {
        queryInput,
        sourceQuery,
        dataLogicKey,
        editingInsight,
        editingView,
        useSceneTabs,
        updateInsightButtonEnabled,
        insightLogicProps,
        changesToSave,
        updatingDataWarehouseSavedQuery,
        inProgressViewEdits,
    } = useValues(logic)
    const { setSourceQuery, saveAsView, saveAsInsight, updateInsight, updateView } = useActions(logic)

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataLogicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: dataLogicKey,
        editMode: true,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: setSourceQuery,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: sourceQuery.source,
        key: dataLogicKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: dataLogicKey,
        variablesOverride: undefined,
        autoLoad: false,
        onData: (data) => {
            const mountedLogic = multitabEditorLogic.findMounted({
                key: codeEditorKey,
                tabId,
                monaco,
                editor,
            })

            if (mountedLogic) {
                mountedLogic.actions.setResponse(data ?? null)
            }
        },
        onError: (error) => {
            const mountedLogic = multitabEditorLogic.findMounted({
                key: codeEditorKey,
                tabId,
                monaco,
                editor,
            })

            if (mountedLogic) {
                mountedLogic.actions.setDataError(error)
            }
        },
    }

    const { loadData } = useActions(dataNodeLogic(dataNodeLogicProps))
    const { response } = useValues(dataNodeLogic(dataNodeLogicProps))

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
        queryInput,
        sourceQuery,
        setQuery: setSourceQuery,
        onUpdate: (query) => {
            loadData('force_async', undefined, query.source)
        },
    }

    const isMaterializedView = editingView?.is_materialized === true
    const editingViewDisabledReason = updatingDataWarehouseSavedQuery
        ? 'Saving...'
        : !response
          ? 'Run query to update'
          : !changesToSave
            ? 'No changes to save'
            : undefined

    return (
        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                    <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                        <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                            <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                                <BindLogic logic={outputPaneLogic} props={{}}>
                                    <BindLogic
                                        logic={multitabEditorLogic}
                                        props={{ key: codeEditorKey, tabId, monaco, editor }}
                                    >
                                        <div
                                            data-attr="editor-scene"
                                            className="EditorScene w-full h-full gap-2 flex flex-col overflow-hidden"
                                            ref={ref}
                                        >
                                            {useSceneTabs ? (
                                                editingInsight ? (
                                                    <BindLogic logic={insightSceneLogic} props={{ tabId }}>
                                                        <BindLogic logic={insightLogic} props={insightLogicProps}>
                                                            <InsightPageHeader insightLogicProps={insightLogicProps} />
                                                        </BindLogic>
                                                    </BindLogic>
                                                ) : (
                                                    <div className="px-4">
                                                        <PageHeader
                                                            buttons={
                                                                <div className="flex items-center gap-2">
                                                                    {!editingInsight && !editingView ? (
                                                                        <>
                                                                            <LemonButton
                                                                                onClick={() => saveAsView()}
                                                                                icon={<IconDownload />}
                                                                                type="tertiary"
                                                                                size="xsmall"
                                                                                data-attr="sql-editor-save-view-button"
                                                                                id="sql-editor-query-window-save-as-view"
                                                                            >
                                                                                Save database view
                                                                            </LemonButton>
                                                                            {editingInsight && (
                                                                                <LemonButton
                                                                                    disabledReason={
                                                                                        !updateInsightButtonEnabled &&
                                                                                        'No updates to save'
                                                                                    }
                                                                                    type="primary"
                                                                                    onClick={() => updateInsight()}
                                                                                    id="sql-editor-update-insight"
                                                                                    sideAction={{
                                                                                        dropdown: {
                                                                                            placement: 'bottom-end',
                                                                                            overlay: (
                                                                                                <LemonMenuOverlay
                                                                                                    items={[
                                                                                                        {
                                                                                                            label: 'Save as...',
                                                                                                            onClick:
                                                                                                                () =>
                                                                                                                    saveAsInsight(),
                                                                                                        },
                                                                                                    ]}
                                                                                                />
                                                                                            ),
                                                                                        },
                                                                                    }}
                                                                                >
                                                                                    Save insight
                                                                                </LemonButton>
                                                                            )}
                                                                            {!editingInsight && (
                                                                                <LemonButton
                                                                                    // disabledReason={!hasColumns ? 'No results to save' : undefined}
                                                                                    type="primary"
                                                                                    onClick={() => saveAsInsight()}
                                                                                    id="sql-editor-save-insight"
                                                                                >
                                                                                    Save insight
                                                                                </LemonButton>
                                                                            )}
                                                                        </>
                                                                    ) : editingView ? (
                                                                        <>
                                                                            <LemonButton
                                                                                onClick={() =>
                                                                                    updateView({
                                                                                        id: editingView.id,
                                                                                        query: {
                                                                                            ...sourceQuery.source,
                                                                                            query: queryInput,
                                                                                        },
                                                                                        types:
                                                                                            response &&
                                                                                            'types' in response
                                                                                                ? (response?.types ??
                                                                                                  [])
                                                                                                : [],
                                                                                        shouldRematerialize:
                                                                                            isMaterializedView,
                                                                                        edited_history_id:
                                                                                            inProgressViewEdits[
                                                                                                editingView.id
                                                                                            ],
                                                                                    })
                                                                                }
                                                                                disabledReason={
                                                                                    editingViewDisabledReason
                                                                                }
                                                                                icon={
                                                                                    updatingDataWarehouseSavedQuery ? (
                                                                                        <Spinner />
                                                                                    ) : (
                                                                                        <IconDownload />
                                                                                    )
                                                                                }
                                                                                type="primary"
                                                                                id={`sql-editor-query-window-update-${isMaterializedView ? 'materialize' : 'view'}`}
                                                                            >
                                                                                {isMaterializedView
                                                                                    ? 'Update and re-materialize view'
                                                                                    : 'Update view'}
                                                                            </LemonButton>
                                                                        </>
                                                                    ) : null}
                                                                </div>
                                                            }
                                                        />
                                                        {editingView ? (
                                                            <SceneTitleSection
                                                                name={editingView.name || ''}
                                                                resourceType={{ type: 'view' }}
                                                                canEdit={false}
                                                            />
                                                        ) : null}
                                                    </div>
                                                )
                                            ) : null}

                                            <QueryWindow
                                                onSetMonacoAndEditor={(monaco, editor) =>
                                                    setMonacoAndEditor([monaco, editor])
                                                }
                                            />
                                        </div>
                                        <ViewLinkModal />
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
