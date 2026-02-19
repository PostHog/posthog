import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useMemo } from 'react'

import { IconBook, IconDownload, IconInfo, IconPlayFilled } from '@posthog/icons'
import { LemonDivider, Spinner } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { IconCancel } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton, SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { OutputPane } from './OutputPane'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { FixErrorButton } from './components/FixErrorButton'
import { draftsLogic } from './draftsLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

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
        insightLoading,
        sourceQuery,
        originalQueryInput,
        suggestedQueryInput,
        isDraft,
        currentDraft,
        changesToSave,
        inProgressViewEdits,
        isEmbeddedMode,
    } = useValues(sqlEditorLogic)

    const {
        setQueryInput,
        runQuery,
        setError,
        setMetadata,
        setMetadataLoading,
        saveAsView,
        saveDraft,
        updateView,
        setSuggestedQueryInput,
        reportAIQueryPromptOpen,
    } = useActions(sqlEditorLogic)
    const { openHistoryModal } = useActions(sqlEditorLogic)

    const { saveOrUpdateDraft } = useActions(draftsLogic)
    const { response } = useValues(dataNodeLogic)
    const { endpoint, isUpdateMode, selectedEndpointName } = useValues(endpointLogic({ tabId }))
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { editorVimModeEnabled } = useValues(userPreferencesLogic)
    const { setEditorVimModeEnabled } = useActions(userPreferencesLogic)
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

    const titleSectionProps = useMemo(() => {
        if (editingInsight) {
            const forceBackTo: Breadcrumb = {
                key: editingInsight.short_id,
                name: 'Back to insight',
                path: urls.insightView(editingInsight.short_id),
                iconType: 'insight/hog',
            }

            return {
                forceBackTo,
                name: editingInsight.name || editingInsight.derived_name || 'Untitled',
                resourceType: { type: 'insight/hog' },
            }
        }

        if (insightLoading) {
            return {
                name: 'Loading insight...',
                resourceType: { type: 'insight/hog' },
            }
        }

        if (editingView) {
            return {
                name: editingView.name,
                resourceType: { type: editingView.is_materialized ? 'matview' : 'view' },
            }
        }

        if (isUpdateMode && selectedEndpointName) {
            const forceBackTo: Breadcrumb = {
                key: selectedEndpointName,
                name: 'Back to endpoint',
                path: urls.endpoint(selectedEndpointName),
                iconType: 'endpoints',
            }

            return {
                forceBackTo,
                name: endpoint?.name || selectedEndpointName,
                resourceType: { type: 'endpoint' },
            }
        }

        return {
            name: 'New SQL query',
            resourceType: { type: 'sql_editor' },
        }
    }, [editingInsight, insightLoading, editingView, isUpdateMode, selectedEndpointName, endpoint?.name])

    return (
        <div className="flex grow flex-col overflow-hidden">
            {!isEmbeddedMode && (
                <SceneTitleSection className="p-1 pl-3 pr-2" noBorder noPadding {...titleSectionProps} />
            )}

            <QueryPane
                originalValue={originalQueryInput ?? ''}
                queryInput={(suggestedQueryInput || queryInput) ?? ''}
                sourceQuery={sourceQuery.source}
                promptError={null}
                onRun={runQuery}
                editorVimModeEnabled={vimModeFeatureEnabled && editorVimModeEnabled}
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

            <div className="flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b py-1">
                <div className="flex items-center gap-2">
                    <RunButton />
                    <LemonDivider vertical />
                    <QueryVariablesMenu
                        disabledReason={editingView ? 'Variables are not allowed in views.' : undefined}
                    />
                </div>

                <div className="ml-auto flex items-center gap-2">
                    {!isEmbeddedMode && isDraft && featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS] && (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
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
                                type="secondary"
                                size="small"
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
                                                types: response && 'types' in response ? (response?.types ?? []) : [],
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
                    {!isEmbeddedMode && editingView && !isDraft && activeTab && (
                        <>
                            {featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS] && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
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
                                type="secondary"
                                size="small"
                                id={`sql-editor-query-window-update-${isMaterializedView ? 'materialize' : 'view'}`}
                            >
                                {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                            </LemonButton>
                        </>
                    )}
                    {!isEmbeddedMode && editingView && (
                        <>
                            <LemonButton
                                onClick={() => openHistoryModal()}
                                icon={<IconBook />}
                                type="secondary"
                                size="small"
                                id="sql-editor-query-window-history"
                            >
                                History
                            </LemonButton>
                        </>
                    )}
                    {!isEmbeddedMode && !editingInsight && !editingView && !insightLoading && (
                        <>
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
                                    type="secondary"
                                    size="small"
                                    data-attr="sql-editor-save-view-button"
                                    id="sql-editor-query-window-save-as-view"
                                >
                                    Save as view
                                </LemonButton>
                            </AppShortcut>
                        </>
                    )}
                    <FixErrorButton type="secondary" size="small" source="action-bar" />
                    {vimModeFeatureEnabled && (
                        <LemonSwitch
                            checked={editorVimModeEnabled}
                            onChange={setEditorVimModeEnabled}
                            label="Vim"
                            size="small"
                            bordered
                            data-attr="sql-editor-vim-toggle"
                        />
                    )}
                    {isRemovingSidePanelFlag && (
                        <SceneTitlePanelButton
                            buttonClassName="size-[26px]"
                            maxToolProps={{
                                identifier: 'execute_sql',
                                context: {
                                    current_query: queryInput,
                                },
                                contextDescription: {
                                    text: 'Current query',
                                    icon: iconForType('sql_editor'),
                                },
                                callback: (toolOutput: string) => {
                                    setSuggestedQueryInput(toolOutput, 'max_ai')
                                },
                                suggestions: [],
                                onMaxOpen: () => {
                                    reportAIQueryPromptOpen()
                                },
                                introOverride: {
                                    headline: 'What data do you want to analyze?',
                                    description: 'Let me help you quickly write SQL, and tweak it.',
                                },
                            }}
                        />
                    )}
                </div>
            </div>
            <InternalQueryWindow tabId={tabId} />

            <QueryHistoryModal />
        </div>
    )
}

function RunButton(): JSX.Element {
    const { runQuery } = useActions(sqlEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { metadata, queryInput, isSourceQueryLastRun } = useValues(sqlEditorLogic)

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
                type="primary"
                size="small"
                tooltip={tooltipContent}
            >
                {responseLoading ? 'Cancel' : 'Run'}
            </LemonButton>
        </AppShortcut>
    )
}

const InternalQueryWindow = memo(function InternalQueryWindow({ tabId }: { tabId: string }): JSX.Element | null {
    const { finishedLoading } = useValues(sqlEditorLogic)

    // NOTE: hacky way to avoid flicker loading
    if (finishedLoading) {
        return null
    }

    return <OutputPane tabId={tabId} />
})
