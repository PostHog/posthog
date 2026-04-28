import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useMemo } from 'react'

import { IconDatabase, IconGear, IconInfo, IconPlayFilled, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { cn } from 'lib/utils/css-classes'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { FixErrorButton } from './components/FixErrorButton'
import { ConnectionSelector } from './ConnectionSelector'
import { editorSizingLogic } from './editorSizingLogic'
import { OutputPane } from './OutputPane'
import { QueryFiltersMenu } from './QueryFiltersMenu'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
    mode?: SQLEditorMode
    showDatabaseTree: boolean
    onShowDatabaseTree: () => void
}

export function QueryWindow({
    onSetMonacoAndEditor,
    tabId,
    mode,
    showDatabaseTree,
    onShowDatabaseTree,
}: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`

    const {
        queryInput,
        sourceQuery,
        originalQueryInput,
        suggestedQueryInput,
        editingView,
        activeQueryText,
        activeQueryOffset,
        selectedConnectionId,
        sendRawQueryEnabled,
    } = useValues(sqlEditorLogic)

    const {
        setQueryInput,
        runQuery,
        runSubquery,
        setError,
        setMetadata,
        setMetadataLoading,
        setSendRawQuery,
        openMaterializationModal,
    } = useActions(sqlEditorLogic)

    const { setSuggestedQueryInput, reportAIQueryPromptOpen } = useActions(sqlEditorLogic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { editorVimModeEnabled } = useValues(userPreferencesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { setEditorVimModeEnabled } = useActions(userPreferencesLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const isDirectQueryEnabled = !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]
    const canSendRawQuery = isDirectQueryEnabled && !!selectedConnectionId
    const sendRawQueryLabel = (
        <span className="inline-flex items-center gap-1">
            <span>Send raw query</span>
            <Tooltip title="Send the query directly to the selected external connection without translating it through HogQL first. This is an escape hatch for SQL syntax that HogQL does not yet support. Your query may be logged to improve the service.">
                <span
                    className="inline-flex cursor-help"
                    onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                    }}
                >
                    <IconInfo className="size-3.5 text-muted-alt" />
                </span>
            </Tooltip>
        </span>
    )

    const editorSettingsItems = [
        ...(vimModeFeatureEnabled
            ? [
                  {
                      custom: true,
                      label: () => (
                          <LemonSwitch
                              checked={editorVimModeEnabled}
                              onChange={setEditorVimModeEnabled}
                              label="Vim mode"
                              size="small"
                              fullWidth
                              data-attr="sql-editor-vim-toggle"
                          />
                      ),
                  },
              ]
            : []),
        ...(canSendRawQuery
            ? [
                  {
                      custom: true,
                      label: () => (
                          <LemonSwitch
                              checked={sendRawQueryEnabled}
                              onChange={setSendRawQuery}
                              label={sendRawQueryLabel}
                              size="small"
                              fullWidth
                              data-attr="sql-editor-send-raw-query-toggle"
                          />
                      ),
                  },
              ]
            : []),
    ]

    return (
        <div className="flex grow flex-col overflow-hidden">
            <div
                className={cn(
                    'flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b border-t py-1',
                    isDatabaseTreeCollapsed || mode !== SQLEditorMode.FullScene ? '' : 'rounded-tl-lg'
                )}
            >
                <div className="flex items-center gap-2">
                    <ExpandDatabaseTreeButton
                        showDatabaseTree={showDatabaseTree}
                        onShowDatabaseTree={onShowDatabaseTree}
                    />
                    <RunButton />
                    <CollapsedConnectionSelector mode={mode} isDirectQueryEnabled={isDirectQueryEnabled} />
                    <LemonDivider vertical />
                    <QueryVariablesMenu
                        disabledReason={editingView ? 'Variables are not allowed in views.' : undefined}
                    />
                    <QueryFiltersMenu />
                    {editingView ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconDatabase />}
                            onClick={() => openMaterializationModal(editingView)}
                            data-attr="sql-editor-materialization-button"
                        >
                            Materialization
                        </LemonButton>
                    ) : null}
                </div>

                <div className="ml-auto flex items-center gap-2">
                    <FixErrorButton type="secondary" size="small" source="action-bar" />
                    {editorSettingsItems.length > 0 ? (
                        <LemonMenu items={editorSettingsItems} closeOnClickInside={false} placement="bottom-end">
                            <LemonButton
                                icon={<IconGear />}
                                type="secondary"
                                size="small"
                                tooltip="Editor settings"
                                data-attr="sql-editor-settings-toggle"
                            />
                        </LemonMenu>
                    ) : null}
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
                    metadataQuery: activeQueryText ?? undefined,
                    metadataQueryOffset: activeQueryOffset,
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
                    onPressCmdShiftEnter: runSubquery,
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

function ExpandDatabaseTreeButton({
    showDatabaseTree,
    onShowDatabaseTree,
}: {
    showDatabaseTree: boolean
    onShowDatabaseTree: () => void
}): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const { toggleDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    if (showDatabaseTree && !isDatabaseTreeCollapsed) {
        return null
    }

    return (
        <LemonButton
            icon={<IconSidebarClose className="size-4 text-tertiary rotate-0" />}
            type="secondary"
            size="small"
            tooltip="Expand database schema panel"
            onClick={() => {
                if (!showDatabaseTree) {
                    onShowDatabaseTree()
                    return
                }
                toggleDatabaseTreeCollapsed()
            }}
        />
    )
}

function RunButton(): JSX.Element {
    const { runQuery, runSubquery } = useActions(sqlEditorLogic)
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

    const sideAction = useMemo(
        () =>
            responseLoading
                ? undefined
                : {
                      dropdown: {
                          placement: 'bottom-end' as const,
                          overlay: (
                              <>
                                  <LemonButton
                                      fullWidth
                                      onClick={() => runQuery()}
                                      sideIcon={<span className="text-muted text-xs">⌘↵</span>}
                                  >
                                      Run query at cursor
                                  </LemonButton>
                                  <LemonButton
                                      fullWidth
                                      onClick={() => runSubquery()}
                                      sideIcon={<span className="text-muted text-xs">⌘⇧↵</span>}
                                  >
                                      Run innermost subquery at cursor
                                  </LemonButton>
                              </>
                          ),
                      },
                  },
        [responseLoading, runQuery, runSubquery]
    )

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
                sideAction={sideAction}
            >
                {responseLoading ? 'Cancel' : 'Run'}
            </LemonButton>
        </AppShortcut>
    )
}

const InternalQueryWindow = memo(function InternalQueryWindow(): JSX.Element | null {
    const { finishedLoading } = useValues(sqlEditorLogic)

    if (finishedLoading) {
        return null
    }

    return <OutputPane />
})

function CollapsedConnectionSelector({
    mode,
    isDirectQueryEnabled,
}: {
    mode?: SQLEditorMode
    isDirectQueryEnabled: boolean
}): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)

    if (!isDirectQueryEnabled || !isDatabaseTreeCollapsed || (mode && mode !== SQLEditorMode.FullScene)) {
        return null
    }

    return <ConnectionSelector />
}
