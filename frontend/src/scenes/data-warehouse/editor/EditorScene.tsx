import './EditorScene.scss'

import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { ItemMode } from '~/types'

import { ViewLinkModal } from '../ViewLinkModal'
import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic } from './outputPaneLogic'
import { QueryWindow } from './QueryWindow'
import { EditorSidebar } from './sidebar/EditorSidebar'
import { editorSidebarLogic } from './sidebar/editorSidebarLogic'

export function EditorScene(): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)
    const sidebarRef = useRef(null)
    const { featureFlags } = useValues(featureFlagLogic)

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

    const { queryInput, sourceQuery, dataLogicKey } = useValues(logic)
    const { setSourceQuery, setResponse, setDataError } = useActions(logic)

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataLogicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: dataLogicKey,
        insightMode: ItemMode.Edit,
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
            setResponse(data ?? null)
        },
        onError: (error) => {
            setDataError(error)
        },
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
                                <BindLogic logic={editorSidebarLogic} props={{ key: dataVisualizationLogicProps.key }}>
                                    <BindLogic logic={outputPaneLogic} props={{}}>
                                        <BindLogic
                                            logic={multitabEditorLogic}
                                            props={{ key: codeEditorKey, monaco, editor }}
                                        >
                                            <div
                                                data-attr="editor-scene"
                                                className="EditorScene w-full h-full flex flex-row overflow-hidden"
                                                ref={ref}
                                            >
                                                {!featureFlags[FEATURE_FLAGS.SQL_EDITOR_TREE_VIEW] && (
                                                    <EditorSidebar
                                                        sidebarRef={sidebarRef}
                                                        codeEditorKey={codeEditorKey}
                                                    />
                                                )}
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
        </BindLogic>
    )
}
