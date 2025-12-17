import './EditorScene.scss'

import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { editor as importedEditor } from 'monaco-editor'
import { useMemo, useRef, useState } from 'react'

import MaxTool from 'scenes/max/MaxTool'
import { SceneExport } from 'scenes/sceneTypes'

import { DatabaseTree } from '~/layout/panel-layout/DatabaseTree/DatabaseTree'
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
import { NodeKind } from '~/queries/schema/schema-general'

import { MAX_AI_ENDPOINT_OPERATION, captureMaxAIEndpointException } from 'products/endpoints/frontend/utils'

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
    const databaseTreeRef = useRef(null)

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
            },
        }),
        []
    )

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

    const maxToolContext = useMemo(() => {
        if (!queryInput) {
            return {}
        }
        return {
            query: {
                kind: NodeKind.HogQLQuery,
                query: queryInput,
            },
            source: 'SQL Editor',
        }
    }, [queryInput])

    return (
        <MaxTool
            identifier="create_endpoint"
            context={maxToolContext}
            callback={(toolOutput: { endpoint_name?: string; url?: string; error?: string }) => {
                if (toolOutput?.error) {
                    captureMaxAIEndpointException(
                        toolOutput.error,
                        MAX_AI_ENDPOINT_OPERATION.CREATE,
                        toolOutput.endpoint_name
                    )
                } else if (toolOutput?.url) {
                    router.actions.push(toolOutput.url)
                }
            }}
            suggestions={['Create an endpoint from this query', 'Expose this as an API']}
        >
            <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                        <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                                <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                                    <BindLogic logic={outputPaneLogic} props={{ tabId }}>
                                        <BindLogic logic={multitabEditorLogic} props={{ tabId, monaco, editor }}>
                                            <div className="flex h-[calc(100vh-var(--scene-layout-header-height))]">
                                                <DatabaseTree databaseTreeRef={databaseTreeRef} />
                                                <div
                                                    data-attr="editor-scene"
                                                    className="EditorScene flex-1 flex flex-row overflow-hidden"
                                                    ref={ref}
                                                >
                                                    <QueryWindow
                                                        tabId={tabId || ''}
                                                        onSetMonacoAndEditor={(monaco, editor) =>
                                                            setMonacoAndEditor([monaco, editor])
                                                        }
                                                    />
                                                </div>
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
        </MaxTool>
    )
}
