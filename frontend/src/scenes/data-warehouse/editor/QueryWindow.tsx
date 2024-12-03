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
import { DataVisualizationNode, NodeKind } from '~/queries/schema'
import { ItemMode } from '~/types'

import { multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'

export function QueryWindow(): JSX.Element {
    const [querySource, localSetQuerySource] = useState({
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: '',
        },
    } as DataVisualizationNode)

    const vizKey = `SQLEditorScene`

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: vizKey,
        query: querySource,
        dashboardId: undefined,
        dataNodeCollectionId: vizKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: localSetQuerySource,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: querySource.source,
        key: vizKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: vizKey,
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
        onRunQuery: (queryInput) => {
            setQuery({
                ...query,
                source: { ...query.source, query: queryInput },
            })
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
        activeTabKey,
        hasErrors,
        error,
        isValidView,
        editingView,
    } = useValues(logic)
    const { selectTab, deleteTab, createTab, setQueryInput, runQuery, saveAsView } = useActions(logic)

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
                logicKey={activeTabKey}
                query={activeQuery ?? ''}
                onQueryInputChange={runQuery}
                onSave={saveAsView}
                saveDisabledReason={
                    hasErrors ? error ?? 'Query has errors' : !isValidView ? 'Some fields may need an alias' : ''
                }
            />
        </div>
    )
}
