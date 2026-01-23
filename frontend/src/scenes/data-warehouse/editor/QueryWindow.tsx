import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { useMemo, useRef, useState } from 'react'

import { IconBook, IconDownload, IconInfo, IconPlayFilled } from '@posthog/icons'
import { LemonDivider, Spinner } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { IconCancel } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema/schema-general'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { OutputPane } from './OutputPane'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryPane } from './QueryPane'
import { CollapsibleSection } from './components/CollapsibleSection'
import { FixErrorButton } from './components/FixErrorButton'
import { draftsLogic } from './draftsLogic'
import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { Endpoint } from './output-pane-tabs/Endpoint'
import { QueryInfo } from './output-pane-tabs/QueryInfo'
import { QueryVariables } from './output-pane-tabs/QueryVariables'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'

const MINIMUM_VARIABLES_PANEL_WIDTH = 260
const VARIABLES_PANEL_DEFAULT_WIDTH = 360
const MAXIMUM_VARIABLES_PANEL_WIDTH = 640

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
}

export function QueryWindow({ onSetMonacoAndEditor, tabId }: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`

    const {
        activeTab,
        queryInput,
        editingView,
        editingInsight,
        sourceQuery,
        originalQueryInput,
        suggestedQueryInput,
        isDraft,
        currentDraft,
        changesToSave,
        inProgressViewEdits,
    } = useValues(multitabEditorLogic)

    const { setQueryInput, runQuery, setError, setMetadata, setMetadataLoading, saveAsView, saveDraft, updateView } =
        useActions(multitabEditorLogic)
    const { openHistoryModal } = useActions(multitabEditorLogic)

    const { saveOrUpdateDraft } = useActions(draftsLogic)
    const { response } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { queryPaneHeight } = useValues(editorSizingLogic)
    const { activeTab: activeOutputTab } = useValues(outputPaneLogic)
    const [isQueryOpen, setIsQueryOpen] = useState(true)
    const [isVariablesPanelOpen, setIsVariablesPanelOpen] = useState(true)
    const variablesPanelRef = useRef<HTMLDivElement>(null)
    const variablesPanelResizerProps = useMemo(
        () => ({
            containerRef: variablesPanelRef,
            logicKey: 'sql-editor-variables-panel',
            placement: 'left' as const,
            persistent: true,
        }),
        []
    )
    const { desiredSize: variablesPanelDesiredSize } = useValues(resizerLogic(variablesPanelResizerProps))
    const [editingViewDisabledReason, EditingViewButtonIcon] = useMemo(() => {
        if (updatingDataWarehouseSavedQuery) {
            return ['Saving...', Spinner]
        }

        if (!response) {
            return ['Run query to update', IconDownload]
        }

        if (!changesToSave) {
            return ['No changes to save', IconDownload]
        }

        return [undefined, IconDownload]
    }, [updatingDataWarehouseSavedQuery, changesToSave, response])

    const isMaterializedView = editingView?.is_materialized === true
    const isEndpointEditing = featureFlags[FEATURE_FLAGS.ENDPOINTS] && activeOutputTab === OutputTab.Endpoint
    const showVariablesToggle = !editingView && !isEndpointEditing
    const isVariablesPanelVisible = showVariablesToggle ? isVariablesPanelOpen : true
    const variablesPanelWidth = Math.min(
        Math.max(variablesPanelDesiredSize ?? VARIABLES_PANEL_DEFAULT_WIDTH, MINIMUM_VARIABLES_PANEL_WIDTH),
        MAXIMUM_VARIABLES_PANEL_WIDTH
    )

    return (
        <div className="flex grow flex-col overflow-hidden">
            {(editingView || editingInsight) && (
                <div className="h-5 bg-warning-highlight">
                    <span className="pl-2 text-xs">
                        {editingView && (
                            <>
                                Editing {isDraft ? 'draft of ' : ''} {isMaterializedView ? 'materialized view' : 'view'}{' '}
                                "{editingView.name}"
                            </>
                        )}
                        {editingInsight && (
                            <>
                                Editing insight "
                                <Link to={urls.insightView(editingInsight.short_id)}>{editingInsight.name}</Link>"
                            </>
                        )}
                    </span>
                </div>
            )}
            <CollapsibleSection
                title="Query"
                isOpen={isQueryOpen}
                onToggle={() => setIsQueryOpen((prev) => !prev)}
                actions={
                    <>
                        <RunButton />
                        <LemonDivider vertical />
                        {isDraft && featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS] && (
                            <>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    id="sql-editor-query-window-save-as-draft"
                                    onClick={() => {
                                        if (editingView) {
                                            saveOrUpdateDraft(
                                                {
                                                    kind: NodeKind.HogQLQuery,
                                                    query: queryInput ?? '',
                                                },
                                                editingView.id,
                                                currentDraft?.id || undefined,
                                                activeTab ?? undefined
                                            )
                                        } else {
                                            saveOrUpdateDraft(
                                                {
                                                    kind: NodeKind.HogQLQuery,
                                                    query: queryInput ?? '',
                                                },
                                                undefined,
                                                currentDraft?.id || undefined,
                                                activeTab ?? undefined
                                            )
                                        }
                                    }}
                                >
                                    Save
                                </LemonButton>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    id="sql-editor-query-window-publish-draft"
                                    disabledReason={editingViewDisabledReason}
                                    onClick={() => {
                                        if (editingView && currentDraft?.id && activeTab) {
                                            updateView(
                                                {
                                                    id: editingView.id,
                                                    query: {
                                                        ...sourceQuery.source,
                                                        query: queryInput ?? '',
                                                    },
                                                    name: editingView.name,
                                                    types:
                                                        response && 'types' in response ? (response?.types ?? []) : [],
                                                    shouldRematerialize: isMaterializedView,
                                                    edited_history_id: activeTab.view?.latest_history_id,
                                                },
                                                currentDraft.id
                                            )
                                        } else {
                                            saveAsView(false, currentDraft?.id)
                                        }
                                    }}
                                    tooltip={
                                        editingView
                                            ? 'Publishing will update the view with these changes.'
                                            : 'The view this draft is based on has been deleted. Publishing will create a new view.'
                                    }
                                >
                                    {!editingView && <IconInfo className="mr-1" color="var(--warning)" />}
                                    Publish
                                </LemonButton>
                            </>
                        )}
                        {editingView && !isDraft && activeTab && (
                            <>
                                {featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS] && (
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        id="sql-editor-query-window-save-draft"
                                        onClick={() => {
                                            saveDraft(activeTab, queryInput ?? '', editingView.id)
                                        }}
                                    >
                                        Save draft
                                    </LemonButton>
                                )}
                                <LemonButton
                                    onClick={() =>
                                        updateView({
                                            id: editingView.id,
                                            query: {
                                                ...sourceQuery.source,
                                                query: queryInput ?? '',
                                            },
                                            types: response && 'types' in response ? (response?.types ?? []) : [],
                                            shouldRematerialize: isMaterializedView,
                                            edited_history_id: inProgressViewEdits[editingView.id],
                                        })
                                    }
                                    disabledReason={editingViewDisabledReason}
                                    icon={<EditingViewButtonIcon />}
                                    type="tertiary"
                                    size="xsmall"
                                    id={`sql-editor-query-window-update-${isMaterializedView ? 'materialize' : 'view'}`}
                                >
                                    {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                </LemonButton>
                            </>
                        )}
                        {editingView && (
                            <LemonButton
                                onClick={() => openHistoryModal()}
                                icon={<IconBook />}
                                type="tertiary"
                                size="xsmall"
                                id="sql-editor-query-window-history"
                            >
                                History
                            </LemonButton>
                        )}
                        {!editingInsight && !editingView && (
                            <AppShortcut
                                name="SQLEditorSaveAsView"
                                keybind={[keyBinds.save]}
                                intent="Save as view"
                                interaction="click"
                                scope={Scene.SQLEditor}
                            >
                                <LemonButton
                                    onClick={() => saveAsView()}
                                    icon={<IconDownload />}
                                    type="tertiary"
                                    size="xsmall"
                                    data-attr="sql-editor-save-view-button"
                                    id="sql-editor-query-window-save-as-view"
                                >
                                    Save as view
                                </LemonButton>
                            </AppShortcut>
                        )}
                        <FixErrorButton type="tertiary" size="xsmall" source="action-bar" />
                        {showVariablesToggle && (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                onClick={() => {
                                    setIsVariablesPanelOpen((prev) => !prev)
                                }}
                            >
                                {isVariablesPanelOpen ? 'Hide variables' : 'Show variables'}
                            </LemonButton>
                        )}
                    </>
                }
            >
                <div className="flex w-full min-h-0">
                    <div className="flex-1 min-w-0">
                        <QueryPane
                            originalValue={originalQueryInput ?? ''}
                            queryInput={(suggestedQueryInput || queryInput) ?? ''}
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
                    </div>
                    {isVariablesPanelVisible && (
                        <div
                            className="relative shrink-0 border-l bg-bg-light dark:bg-black"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ height: `${queryPaneHeight}px`, width: `${variablesPanelWidth}px` }}
                            ref={variablesPanelRef}
                        >
                            <div className="h-full overflow-y-auto p-4">
                                {editingView ? (
                                    <QueryInfo tabId={tabId} />
                                ) : isEndpointEditing ? (
                                    <Endpoint tabId={tabId} />
                                ) : (
                                    <QueryVariables />
                                )}
                            </div>
                            <Resizer {...variablesPanelResizerProps} />
                        </div>
                    )}
                </div>
            </CollapsibleSection>
            <InternalQueryWindow />
            <QueryHistoryModal />
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

        if (!metadata || isUsingIndices || queryInput?.trim().length === 0) {
            return ['var(--success)', 'New changes to run']
        }

        const tooltipContent = !isUsingIndices
            ? 'This query is not using indices optimally, which may result in slower performance.'
            : undefined

        return ['var(--warning)', tooltipContent]
    }, [metadata, isUsingIndices, queryInput, isSourceQueryLastRun])

    return (
        <AppShortcut
            name="SQLEditorRun"
            keybind={[keyBinds.run]}
            intent={responseLoading ? 'Cancel query' : 'Run query'}
            interaction="click"
            scope={Scene.SQLEditor}
        >
            <LemonButton
                data-attr="sql-editor-run-button"
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
        </AppShortcut>
    )
}

function InternalQueryWindow(): JSX.Element | null {
    const { finishedLoading } = useValues(multitabEditorLogic)

    // NOTE: hacky way to avoid flicker loading
    if (finishedLoading) {
        return null
    }

    return <OutputPane />
}
