import './EditorScene.scss'

import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { editor as importedEditor } from 'monaco-editor'
import { useRef, useState } from 'react'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import {
    variablesLogic,
    VariablesLogicProps,
} from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { DataVisualizationLogicProps } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { ChartDisplayType, ItemMode } from '~/types'

import { ViewLinkModal } from '../ViewLinkModal'
import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { dataNodeKey } from './multitabEditorLogic'
import { QueryWindow } from './QueryWindow'
import { EditorSidebar } from './sidebar/EditorSidebar'

export function EditorScene(): JSX.Element {
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
    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const logic = multitabEditorLogic({
        key: codeEditorKey,
        monaco,
        editor,
    })

    const { activeModelUri, queryInput, sourceQuery } = useValues(logic)
    const { setSourceQuery } = useActions(logic)

    const logicKey = activeModelUri?.uri.path ?? dataNodeKey

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: logicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: logicKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        defaultVisualizationType: ChartDisplayType.ActionsLineGraph,
        setQuery: setSourceQuery,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: sourceQuery.source,
        key: logicKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: logicKey,
        variablesOverride: undefined,
        autoLoad: false,
    }

    const { loadData } = useActions(dataNodeLogic(dataNodeLogicProps))

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

    return (
        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                    <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                        <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                            <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                                <BindLogic logic={multitabEditorLogic} props={{ key: codeEditorKey, monaco, editor }}>
                                    <div className="EditorScene w-full h-full flex flex-row overflow-hidden" ref={ref}>
                                        <EditorSidebar sidebarRef={sidebarRef} codeEditorKey={codeEditorKey} />
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
    )
}
