import { Monaco } from '@monaco-editor/react'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import {
    activemodelStateKey,
    codeEditorLogic,
    CodeEditorLogicProps,
    editorModelsStateKey,
} from 'lib/monaco/codeEditorLogic'
import type { editor as importedEditor, Uri } from 'monaco-editor'
import { useCallback, useEffect, useState } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { hogQLQueryEditorLogic } from '~/queries/nodes/HogQLQuery/hogQLQueryEditorLogic'
import { HogQLQuery, NodeKind } from '~/queries/schema'

import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'
import { ResultPane } from './ResultPane'

export function QueryWindow(): JSX.Element {
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []

    const key = router.values.location.pathname

    const [query, setActiveQueryInput] = useState<HogQLQuery>({
        kind: NodeKind.HogQLQuery,
        query: '',
    })

    const hogQLQueryEditorLogicProps = {
        query,
        setQuery: (query: HogQLQuery) => {
            setActiveQueryInput(query)
        },
        onChange: () => {},
        key,
    }
    const logic = hogQLQueryEditorLogic(hogQLQueryEditorLogicProps)
    const { queryInput, promptError } = useValues(logic)
    const { setQueryInput, saveQuery, saveAsView } = useActions(logic)

    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const codeEditorLogicProps: CodeEditorLogicProps = {
        key: codeEditorKey,
        sourceQuery: query,
        query: queryInput,
        language: 'hogQL',
        metadataFilters: query.filters,
        monaco,
        editor,
        multitab: true,
    }
    const { activeModelUri, allModels, hasErrors, error, isValidView } = useValues(
        codeEditorLogic(codeEditorLogicProps)
    )

    const { createModel, setModel, deleteModel, setModels, addModel, updateState } = useActions(
        codeEditorLogic(codeEditorLogicProps)
    )

    const modelKey = `hogQLQueryEditor/${activeModelUri?.path}`

    useEffect(() => {
        if (monaco && activeModelUri) {
            const _model = monaco.editor.getModel(activeModelUri)
            const val = _model?.getValue()
            setQueryInput(val ?? '')
            saveQuery()
        }
    }, [activeModelUri])

    const onAdd = useCallback(() => {
        createModel()
    }, [createModel])

    return (
        <div className="flex flex-1 flex-col h-full">
            <QueryTabs
                models={allModels}
                onClick={setModel}
                onClear={deleteModel}
                onAdd={onAdd}
                activeModelUri={activeModelUri}
            />
            <QueryPane
                queryInput={queryInput}
                promptError={promptError}
                codeEditorProps={{
                    onChange: (v) => {
                        setQueryInput(v ?? '')
                        updateState()
                    },
                    onMount: (editor, monaco) => {
                        setMonacoAndEditor([monaco, editor])

                        const allModelQueries = localStorage.getItem(editorModelsStateKey(codeEditorKey))
                        const activeModelUri = localStorage.getItem(activemodelStateKey(codeEditorKey))

                        if (allModelQueries) {
                            // clear existing models
                            monaco.editor.getModels().forEach((model) => {
                                model.dispose()
                            })

                            const models = JSON.parse(allModelQueries || '[]')
                            const newModels: Uri[] = []

                            models.forEach((model: Record<string, any>) => {
                                if (monaco) {
                                    const uri = monaco.Uri.parse(model.path)
                                    const newModel = monaco.editor.createModel(model.query, 'hogQL', uri)
                                    editor?.setModel(newModel)
                                    newModels.push(uri)
                                }
                            })

                            setModels(newModels)

                            if (activeModelUri) {
                                const uri = monaco.Uri.parse(activeModelUri)
                                const activeModel = monaco.editor
                                    .getModels()
                                    .find((model) => model.uri.path === uri.path)
                                activeModel && editor?.setModel(activeModel)
                                const val = activeModel?.getValue()
                                if (val) {
                                    setQueryInput(val)
                                    saveQuery()
                                }
                                setModel(uri)
                            } else if (newModels.length) {
                                setModel(newModels[0])
                            }
                        } else {
                            const model = editor.getModel()

                            if (model) {
                                addModel(model.uri)
                                setModel(model.uri)
                            }
                        }
                    },
                    onPressCmdEnter: (value, selectionType) => {
                        if (value && selectionType === 'selection') {
                            saveQuery(value)
                        } else {
                            saveQuery()
                        }
                    },
                }}
            />
            <BindLogic
                logic={dataNodeLogic}
                props={{
                    key: modelKey,
                    query: query,
                    doNotLoad: !query.query,
                }}
            >
                <ResultPane
                    onQueryInputChange={saveQuery}
                    onSave={saveAsView}
                    saveDisabledReason={
                        hasErrors ? error ?? 'Query has errors' : !isValidView ? 'All fields must have an alias' : ''
                    }
                />
            </BindLogic>
        </div>
    )
}
