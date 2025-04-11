import { Monaco } from '@monaco-editor/react'
import { IconBolt, IconDownload, IconPlayFilled, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import type { editor as importedEditor } from 'monaco-editor'
import { useMemo } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'
import { editorSidebarLogic, EditorSidebarTab } from './sidebar/editorSidebarLogic'

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
}

export function QueryWindow({ onSetMonacoAndEditor }: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const { allTabs, activeModelUri, queryInput, editingView, editingInsight, sourceQuery, suggestedQueryInput } =
        useValues(multitabEditorLogic)
    const {
        renameTab,
        selectTab,
        deleteTab,
        createTab,
        setQueryInput,
        runQuery,
        setError,
        setMetadata,
        setMetadataLoading,
        saveAsView,
    } = useActions(multitabEditorLogic)

    const { response } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)
    const { resetDefaultSidebarWidth } = useActions(editorSizingLogic)
    const { setActiveTab } = useActions(editorSidebarLogic)

    const isMaterializedView = !!editingView?.status

    return (
        <div className="flex flex-1 flex-col h-full overflow-hidden">
            <div className="flex flex-row overflow-x-auto">
                {sidebarWidth === 0 && (
                    <LemonButton
                        onClick={() => resetDefaultSidebarWidth()}
                        className="rounded-none"
                        icon={<IconSidebarClose />}
                        type="tertiary"
                        size="small"
                    />
                )}
                <QueryTabs
                    models={allTabs}
                    onClick={selectTab}
                    onClear={deleteTab}
                    onAdd={createTab}
                    onRename={renameTab}
                    activeModelUri={activeModelUri}
                />
            </div>
            {(editingView || editingInsight) && (
                <div className="h-5 bg-warning-highlight">
                    <span className="pl-2 text-xs">
                        {editingView && (
                            <>
                                Editing {isMaterializedView ? 'materialized view' : 'view'} "{editingView.name}"
                            </>
                        )}
                        {editingInsight && <>Editing insight "{editingInsight.name}"</>}
                    </span>
                </div>
            )}
            <div className="flex flex-row justify-start align-center w-full ml-2 mr-2">
                <RunButton />
                <LemonDivider vertical />
                {editingView ? (
                    <LemonButton
                        onClick={() =>
                            updateDataWarehouseSavedQuery({
                                id: editingView.id,
                                query: {
                                    ...sourceQuery.source,
                                    query: queryInput,
                                },
                                types: response?.types ?? [],
                                shouldRematerialize: isMaterializedView,
                            })
                        }
                        disabledReason={updatingDataWarehouseSavedQuery ? 'Saving...' : ''}
                        icon={<IconDownload />}
                        type="tertiary"
                        size="xsmall"
                        id={`sql-editor-query-window-update-${isMaterializedView ? 'materialize' : 'view'}`}
                    >
                        {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton
                            onClick={() => saveAsView()}
                            icon={<IconDownload />}
                            type="tertiary"
                            size="xsmall"
                            id="sql-editor-query-window-save-as-view"
                        >
                            Save as view
                        </LemonButton>
                        <LemonButton
                            onClick={() => setActiveTab(EditorSidebarTab.QueryInfo)}
                            icon={<IconBolt />}
                            type="tertiary"
                            size="xsmall"
                            id="sql-editor-query-window-materialize"
                        >
                            Materialize
                        </LemonButton>
                    </>
                )}
            </div>
            <QueryPane
                originalValue={suggestedQueryInput && suggestedQueryInput != queryInput ? queryInput ?? ' ' : undefined}
                queryInput={suggestedQueryInput && suggestedQueryInput != queryInput ? suggestedQueryInput : queryInput}
                sourceQuery={sourceQuery.source}
                promptError={null}
                onRun={runQuery}
                codeEditorProps={{
                    queryKey: codeEditorKey,
                    onChange: (v) => {
                        setQueryInput(v ?? '')
                    },
                    onMount: (editor, monaco) => {
                        onSetMonacoAndEditor(monaco, editor)
                    },
                    onPressCmdEnter: (value, selectionType) => {
                        if (value && selectionType === 'selection') {
                            runQuery(value)
                        } else {
                            runQuery()
                        }
                    },
                    onError: (error) => {
                        setError(error)
                    },
                    onMetadata: (metadata) => {
                        setMetadata(metadata)
                    },
                    onMetadataLoading: (loading) => {
                        setMetadataLoading(loading)
                    },
                }}
            />
            <InternalQueryWindow />
        </div>
    )
}

function RunButton(): JSX.Element {
    const { runQuery } = useActions(multitabEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { metadata, queryInput, isSourceQueryLastRun } = useValues(multitabEditorLogic)

    const isUsingIndices = metadata?.isUsingIndices === 'yes'

    const [iconColor, tooltipContent] = useMemo(() => {
        if (isSourceQueryLastRun) {
            return ['var(--primary)', 'No changes to run']
        }

        if (!metadata || isUsingIndices || queryInput.trim().length === 0) {
            return ['var(--success)', 'New changes to run']
        }

        const tooltipContent = !isUsingIndices
            ? 'This query is not using indices optimally, which may result in slower performance.'
            : undefined

        return ['var(--warning)', tooltipContent]
    }, [metadata, isUsingIndices, queryInput, isSourceQueryLastRun])

    return (
        <LemonButton
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    runQuery()
                }
            }}
            icon={responseLoading ? <IconCancel /> : <IconPlayFilled color={iconColor} />}
            type="tertiary"
            size="xsmall"
            tooltip={tooltipContent}
        >
            {responseLoading ? 'Cancel' : 'Run'}
        </LemonButton>
    )
}

function InternalQueryWindow(): JSX.Element | null {
    const { cacheLoading } = useValues(multitabEditorLogic)

    // NOTE: hacky way to avoid flicker loading
    if (cacheLoading) {
        return null
    }

    return <OutputPane />
}
