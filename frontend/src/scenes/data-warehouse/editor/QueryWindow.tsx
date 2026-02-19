import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useMemo } from 'react'

import { IconBook, IconChevronDown, IconDownload, IconPlayFilled, IconSidebarClose } from '@posthog/icons'
import { LemonDivider, Spinner } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { IconCancel } from 'lib/lemon-ui/icons'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton, SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { OutputPane } from './OutputPane'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { FixErrorButton } from './components/FixErrorButton'
import { editorSizingLogic } from './editorSizingLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
}

export function QueryWindow({ onSetMonacoAndEditor, tabId }: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`

    const {
        queryInput,
        editingView,
        editingInsight,
        editingEndpoint,
        insightLoading,
        sourceQuery,
        originalQueryInput,
        suggestedQueryInput,
        changesToSave,
        inProgressViewEdits,
        isEmbeddedMode,
        titleSectionProps,
        updateInsightButtonEnabled,
    } = useValues(sqlEditorLogic)

    const {
        setQueryInput,
        runQuery,
        setError,
        setMetadata,
        setMetadataLoading,
        updateView,
        updateInsight,
        updateEndpoint,
        saveAsInsight,
        saveAsView,
        saveAsEndpoint,
        setSuggestedQueryInput,
        reportAIQueryPromptOpen,
    } = useActions(sqlEditorLogic)
    const { openHistoryModal } = useActions(sqlEditorLogic)

    const { response } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
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

    const actionsRow = (
        <div className="flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b py-1">
            <div className="flex items-center gap-2">
                <ExpandDatabaseTreeButton />
                <RunButton />
                <LemonDivider vertical />
                <QueryVariablesMenu disabledReason={editingView ? 'Variables are not allowed in views.' : undefined} />
            </div>

            <div className="ml-auto flex items-center gap-2">
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
    )

    return (
        <div className="flex grow flex-col overflow-hidden">
            {!isEmbeddedMode && (
                <SceneTitleSection
                    className="p-1 pl-3 pr-2"
                    noBorder
                    noPadding
                    {...titleSectionProps}
                    actions={
                        <div className="flex items-center gap-2">
                            {editingView ? (
                                <>
                                    <LemonButton
                                        onClick={() => openHistoryModal()}
                                        icon={<IconBook />}
                                        type="secondary"
                                        size="small"
                                    >
                                        History
                                    </LemonButton>
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
                                        type="primary"
                                        size="small"
                                    >
                                        {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                    </LemonButton>
                                </>
                            ) : editingInsight ? (
                                <LemonButton
                                    disabledReason={!updateInsightButtonEnabled ? 'No updates to save' : undefined}
                                    loading={insightLoading}
                                    type="primary"
                                    size="small"
                                    onClick={() => updateInsight()}
                                >
                                    Update insight
                                </LemonButton>
                            ) : editingEndpoint ? (
                                <LemonButton type="primary" size="small" onClick={() => updateEndpoint()}>
                                    Update endpoint
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={() => saveAsInsight()}
                                    sideIcon={<IconChevronDown />}
                                    sideAction={{
                                        dropdown: {
                                            placement: 'bottom-end',
                                            overlay: (
                                                <LemonMenuOverlay
                                                    items={[
                                                        {
                                                            label: 'Save as view',
                                                            onClick: () => saveAsView(),
                                                        },
                                                        {
                                                            label: 'Save as endpoint',
                                                            onClick: () => saveAsEndpoint(),
                                                        },
                                                    ]}
                                                />
                                            ),
                                        },
                                    }}
                                >
                                    Save as insight
                                </LemonButton>
                            )}
                        </div>
                    }
                />
            )}

            {actionsRow}

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

            <InternalQueryWindow tabId={tabId} />

            <QueryHistoryModal />
        </div>
    )
}

function ExpandDatabaseTreeButton(): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const { toggleDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    if (!isDatabaseTreeCollapsed) {
        return null
    }

    return (
        <LemonButton
            icon={<IconSidebarClose className="size-4 text-tertiary rotate-0" />}
            type="secondary"
            size="small"
            tooltip="Expand panel"
            onClick={toggleDatabaseTreeCollapsed}
        />
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

    if (finishedLoading) {
        return null
    }

    return <OutputPane tabId={tabId} />
})
