import { Monaco } from '@monaco-editor/react'
import { Spinner } from '@posthog/lemon-ui'
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
import { ItemMode } from '~/types'

import { dataNodeKey, multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'

export function QueryWindow(): JSX.Element {
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

    const { allTabs, activeModelUri, queryInput, editingView, sourceQuery } = useValues(logic)
    const { selectTab, deleteTab, createTab, setQueryInput, runQuery, setError, setIsValidView } = useActions(logic)

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
                sourceQuery={sourceQuery.source}
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
                    onError: (error, isValidView) => {
                        setError(error)
                        setIsValidView(isValidView)
                    },
                }}
            />
            <BindLogic logic={multitabEditorLogic} props={{ key: codeEditorKey, monaco, editor }}>
                <InternalQueryWindow />
            </BindLogic>
        </div>
    )
}

function InternalQueryWindow(): JSX.Element {
    const { cacheLoading, sourceQuery, queryInput } = useValues(multitabEditorLogic)
    const { setSourceQuery } = useActions(multitabEditorLogic)

    if (cacheLoading) {
        return (
            <div className="flex-1 flex justify-center items-center">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: dataNodeKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: dataNodeKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: setSourceQuery,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: sourceQuery.source,
        key: dataNodeKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: dataNodeKey,
        variablesOverride: undefined,
        autoLoad: false,
    }

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
        queryInput,
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <OutputPane />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
