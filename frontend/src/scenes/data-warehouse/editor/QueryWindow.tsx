import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { editor as importedEditor } from 'monaco-editor'
import { useState } from 'react'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import {
    variablesLogic,
    VariablesLogicProps,
} from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import {
    dataVisualizationLogic,
    DataVisualizationLogicProps,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { DataVisualizationNode, NodeKind } from '~/queries/schema'
import { ItemMode } from '~/types'

import { DATAWAREHOUSE_EDITOR_ITEM_ID } from '../external/dataWarehouseExternalSceneLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'

const dataNodeKey = insightVizDataNodeKey({
    dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
    cachedInsight: null,
    doNotLoad: true,
})

export function QueryWindow(): JSX.Element {
    const [querySource, localSetQuerySource] = useState({
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: '',
        },
    } as DataVisualizationNode)

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataNodeKey,
        query: querySource,
        dashboardId: undefined,
        dataNodeCollectionId: dataNodeKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: localSetQuerySource,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: querySource.source,
        key: dataNodeKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: dataNodeKey,
        variablesOverride: undefined,
    }

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <InternalQueryWindow setQuery={localSetQuerySource} query={querySource} />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

interface InternalQueryWindowProps {
    setQuery: (query: DataVisualizationNode) => void
    query: DataVisualizationNode
}

function InternalQueryWindow({ setQuery, query }: InternalQueryWindowProps): JSX.Element {
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const { setEditorQuery } = useActions(variablesLogic)

    const logic = multitabEditorLogic({
        key: codeEditorKey,
        monaco,
        editor,
        sourceQuery: query,
        onRunQuery: (query) => {
            setQuery({
                kind: NodeKind.DataVisualizationNode,
                source: query,
            } as DataVisualizationNode)
        },
        onQueryInputChange: (queryInput) => {
            setEditorQuery(queryInput)
        },
    })

    const {
        allTabs,
        activeModelUri,
        queryInput,
        activeQuery,
        hasErrors,
        error,
        isValidView,
        editingView,
        exportContext,
    } = useValues(logic)
    const { selectTab, deleteTab, createTab, setQueryInput, runQuery, saveAsView, saveAsInsight } = useActions(logic)

    return (
        <div className="flex flex-1 flex-col h-full">
            <QueryTabs
                models={allTabs}
                onClick={selectTab}
                onClear={deleteTab}
                onAdd={createTab}
                activeModelUri={activeModelUri}
            />
            {editingView && (
                <div className="h-7 bg-warning-highlight p-1">
                    <span> Editing view "{editingView.name}"</span>
                </div>
            )}
            <QueryPane
                queryInput={queryInput}
                sourceQuery={query.source}
                promptError={null}
                codeEditorProps={{
                    queryKey: codeEditorKey,
                    onChange: (v) => {
                        setQueryInput(v ?? '')
                    },
                    onMount: (editor, monaco) => {
                        setMonacoAndEditor([monaco, editor])
                    },
                    onPressCmdEnter: (value, selectionType) => {
                        if (value && selectionType === 'selection') {
                            runQuery(value)
                        } else {
                            runQuery()
                        }
                    },
                }}
            />
            <OutputPane
                query={activeQuery ?? ''}
                onQueryInputChange={runQuery}
                onQueryChange={setQuery}
                onSaveView={saveAsView}
                onSaveInsight={saveAsInsight}
                exportContext={exportContext}
                saveDisabledReason={
                    hasErrors ? error ?? 'Query has errors' : !isValidView ? 'Some fields may need an alias' : ''
                }
            />
        </div>
    )
}
