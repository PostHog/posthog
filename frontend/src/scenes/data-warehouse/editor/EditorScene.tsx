import './EditorScene.scss'

import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { useRef, useState } from 'react'

import { SceneExport } from 'scenes/sceneTypes'

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
    logic: multitabEditorLogic,
    component: EditorScene,
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

    const logic = multitabEditorLogic({
        tabId: tabId || '',
        monaco,
        editor,
    })

    const { queryInput, sourceQuery, dataLogicKey } = useValues(logic)
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
            const mountedLogic = multitabEditorLogic.findMounted({
                tabId: tabId || '',
                monaco,
                editor,
            })

            if (mountedLogic) {
                mountedLogic.actions.setDataError(error)
            }
        },
    }

    const { loadData } = useActions(dataNodeLogic(dataNodeLogicProps))

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
        queryInput: queryInput ?? '',
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
                                    <BindLogic logic={multitabEditorLogic} props={{ tabId, monaco, editor }}>
                                        <div
                                            data-attr="editor-scene"
                                            className="EditorScene w-full h-[calc(var(--scene-layout-rect-height)-var(--scene-layout-header-height))] flex flex-row overflow-hidden"
                                            ref={ref}
                                        >
                                            <QueryWindow
                                                tabId={tabId || ''}
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
