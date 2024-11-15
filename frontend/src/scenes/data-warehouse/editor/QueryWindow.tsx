import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { editor as importedEditor } from 'monaco-editor'
import { useState } from 'react'

import { multitabEditorLogic } from './multitabEditorLogic'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'
import { ResultPane } from './ResultPane'

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
            <ResultPane
                logicKey={activeTabKey}
                query={activeQuery ?? ''}
                onQueryInputChange={runQuery}
                onSave={saveAsView}
                saveDisabledReason={
                    hasErrors ? error ?? 'Query has errors' : !isValidView ? 'All fields must have an alias' : ''
                }
            />
        </div>
    )
}
