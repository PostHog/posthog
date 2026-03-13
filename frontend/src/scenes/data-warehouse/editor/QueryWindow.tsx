import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useMemo } from 'react'

import { IconPlayFilled, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { cn } from 'lib/utils/css-classes'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { FixErrorButton } from './components/FixErrorButton'
import { editorSizingLogic } from './editorSizingLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
    mode?: SQLEditorMode
}

export function QueryWindow({ onSetMonacoAndEditor, tabId, mode }: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`

    const { queryInput, sourceQuery, originalQueryInput, suggestedQueryInput, editingView } = useValues(sqlEditorLogic)

    const { setQueryInput, runQuery, setError, setMetadata, setMetadataLoading } = useActions(sqlEditorLogic)

    const { setSuggestedQueryInput, reportAIQueryPromptOpen } = useActions(sqlEditorLogic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { editorVimModeEnabled } = useValues(userPreferencesLogic)
    const { setEditorVimModeEnabled } = useActions(userPreferencesLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)

    return (
        <div className="flex grow flex-col overflow-hidden">
            <div
                className={cn(
                    'flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b border-t py-1',
                    isDatabaseTreeCollapsed || mode !== SQLEditorMode.FullScene ? '' : 'rounded-tl-lg'
                )}
            >
                <div className="flex items-center gap-2">
                    <ExpandDatabaseTreeButton />
                    <RunButton />
                    <LemonDivider vertical />
                    <QueryVariablesMenu
                        disabledReason={editingView ? 'Variables are not allowed in views.' : undefined}
                    />
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
                    {mode === SQLEditorMode.Embedded && (
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
            tooltip="Expand database schema panel"
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

        const tooltip = !isUsingIndices
            ? 'This query is not using indices optimally, which may result in slower performance.'
            : undefined

        return ['var(--warning)', tooltip]
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
