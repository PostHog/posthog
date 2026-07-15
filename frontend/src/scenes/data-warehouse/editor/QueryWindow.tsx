import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useCallback, useMemo, useRef } from 'react'

import { IconDatabase, IconGear, IconInfo, IconPlayFilled, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { cn } from 'lib/utils/css-classes'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FixErrorButton } from './components/FixErrorButton'
import { ConnectionSelector } from './ConnectionSelector'
import { editorSizingLogic } from './editorSizingLogic'
import { applyExecuteSqlToolOutput, getExecuteSqlToolContext } from './maxSqlTool'
import { OutputPane } from './OutputPane'
import { QueryFiltersMenu } from './QueryFiltersMenu'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { sqlEditorLogic, tabModelPath } from './sqlEditorLogic'

const EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS = 150

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
    mode?: SQLEditorMode
    showDatabaseTree: boolean
    onShowDatabaseTree: () => void
    showQueryPanel?: boolean
    showOutputPanel?: boolean
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    /** With onRunQuery: flips the button to Cancel while runQueryLoading, mirroring the native cancel. */
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
    onShareTab?: () => void
    /** Whether the query pane's code editor may grab focus on mount. Defaults to true. */
    autoFocusQueryPane?: boolean
}

export function QueryWindow({
    onSetMonacoAndEditor,
    tabId,
    mode,
    showDatabaseTree,
    onShowDatabaseTree,
    showQueryPanel = true,
    showOutputPanel = true,
    onRunQuery,
    runQueryLoading,
    runQueryDisabledReason,
    runQueryTooltip,
    onCancelQuery,
    cancelQueryLoading,
    onShareTab,
    autoFocusQueryPane,
}: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`
    const logic = sqlEditorLogic({ tabId })

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
    } = useValues(logic)

    const {
        setQueryInput,
        runQuery,
        runSubquery,
        setError,
        setMetadata,
        setMetadataLoading,
        setSendRawQuery,
        openMaterializationModal,
        setSourceQuery,
    } = useActions(logic)

    const { setSuggestedQueryInput, reportAIQueryPromptOpen } = useActions(logic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { editorVimModeEnabled } = useValues(userPreferencesLogic)
    const { setEditorVimModeEnabled } = useActions(userPreferencesLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const canSendRawQuery = !!selectedConnectionId
    const debouncedMaxToolQueryInput = useDebouncedValue(queryInput, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const debouncedMaxToolSourceQuery = useDebouncedValue(sourceQuery, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const executeSqlToolStateRef = useRef({ queryInput, sourceQuery })
    executeSqlToolStateRef.current = { queryInput, sourceQuery }
    const executeSqlToolContext = useMemo(
        () => getExecuteSqlToolContext(debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery),
        [debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery]
    )
    const executeSqlToolContextDescription = useMemo(
        () => ({
            text: 'Current query',
            icon: iconForType('sql_editor'),
        }),
        []
    )
    const executeSqlToolIntroOverride = useMemo(
        () => ({
            headline: 'What data do you want to analyze?',
            description: 'Let me help you quickly write SQL, and tweak it.',
        }),
        []
    )
    const executeSqlToolSuggestions = useMemo(() => [], [])
    const handleExecuteSqlToolOutput = useCallback(
        (toolOutput: unknown) => {
            const { queryInput, sourceQuery } = executeSqlToolStateRef.current
            applyExecuteSqlToolOutput({
                toolOutput,
                queryInput,
                sourceQuery,
                setSourceQuery,
                setSuggestedQueryInput,
            })
        },
        [setSourceQuery, setSuggestedQueryInput]
    )
    const executeSqlMaxToolProps = useMemo(
        () => ({
            identifier: 'execute_sql' as const,
            context: executeSqlToolContext,
            contextDescription: executeSqlToolContextDescription,
            callback: handleExecuteSqlToolOutput,
            suggestions: executeSqlToolSuggestions,
            onMaxOpen: reportAIQueryPromptOpen,
            introOverride: executeSqlToolIntroOverride,
        }),
        [
            executeSqlToolContext,
            executeSqlToolContextDescription,
            executeSqlToolIntroOverride,
            executeSqlToolSuggestions,
            handleExecuteSqlToolOutput,
            reportAIQueryPromptOpen,
        ]
    )
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
            {showQueryPanel ? (
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
                        <RunButton
                            onRunQuery={onRunQuery}
                            runQueryLoading={runQueryLoading}
                            runQueryDisabledReason={runQueryDisabledReason}
                            runQueryTooltip={runQueryTooltip}
                            onCancelQuery={onCancelQuery}
                            cancelQueryLoading={cancelQueryLoading}
                        />
                        <CollapsedConnectionSelector tabId={tabId} mode={mode} />
                        <LemonDivider vertical />
                        <QueryVariablesMenu
                            disabledReason={editingView ? 'Variables are not allowed in views.' : undefined}
                        />
                        <QueryFiltersMenu />
                        {editingView ? (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconDatabase />}
                                    onClick={() => openMaterializationModal(editingView)}
                                    data-attr="sql-editor-materialization-button"
                                >
                                    Materialization
                                </LemonButton>
                            </AccessControlAction>
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
                                maxToolProps={executeSqlMaxToolProps}
                            />
                        )}
                    </div>
                </div>
            ) : null}

            {showQueryPanel ? (
                <QueryPane
                    originalValue={originalQueryInput ?? ''}
                    queryInput={(suggestedQueryInput || queryInput) ?? ''}
                    sourceQuery={sourceQuery.source}
                    promptError={null}
                    onRun={runQuery}
                    editorVimModeEnabled={vimModeFeatureEnabled && editorVimModeEnabled}
                    constrainHeight={showOutputPanel}
                    codeEditorProps={{
                        queryKey: codeEditorKey,
                        autoFocus: autoFocusQueryPane ?? true,
                        // Bind the editor to the tab's persistent Monaco model and keep it
                        // alive across the diff <-> editor swap, so undo history survives an
                        // accepted AI suggestion. Shares the URI with the model createTab makes.
                        path: tabModelPath(tabId),
                        keepCurrentModel: true,
                        metadataQuery: activeQueryText ?? undefined,
                        metadataQueryOffset: activeQueryOffset,
                        onChange: (v) => {
                            setQueryInput(v ?? '')
                        },
                        onMount: (editor, monaco) => {
                            onSetMonacoAndEditor(monaco, editor)
                        },
                        onPressCmdEnter: (value, selectionType) => {
                            if (onRunQuery) {
                                if (!runQueryLoading) {
                                    onRunQuery()
                                }
                                return
                            }
                            if (value && selectionType === 'selection') {
                                runQuery(value)
                            } else {
                                runQuery()
                            }
                        },
                        onPressCmdShiftEnter: onRunQuery
                            ? () => {
                                  if (!runQueryLoading) {
                                      onRunQuery()
                                  }
                              }
                            : runSubquery,
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
            ) : null}

            {showOutputPanel ? <InternalQueryWindow tabId={tabId} onShareTab={onShareTab} /> : null}
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

function RunButton({
    onRunQuery,
    runQueryLoading,
    runQueryDisabledReason,
    runQueryTooltip,
    onCancelQuery,
    cancelQueryLoading,
}: {
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
}): JSX.Element {
    const { runQuery, runSubquery } = useActions(sqlEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { metadata, queryInput, isSourceQueryLastRun } = useValues(sqlEditorLogic)

    const isUsingIndices = metadata?.isUsingIndices === 'yes'
    const isRunning = onRunQuery ? !!runQueryLoading : responseLoading
    // The external-run path shows a cancel affordance only when a canceller is provided.
    const showCancel = isRunning && (!onRunQuery || !!onCancelQuery)

    const [iconColor, tooltipContent] = useMemo(() => {
        if (onRunQuery) {
            if (isRunning && onCancelQuery) {
                return ['var(--success)', 'Stop the running query']
            }
            return ['var(--success)', runQueryTooltip ?? 'Run query']
        }

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
    }, [
        metadata,
        isUsingIndices,
        queryInput,
        isSourceQueryLastRun,
        onRunQuery,
        runQueryTooltip,
        isRunning,
        onCancelQuery,
    ])

    const sideAction = useMemo(
        () =>
            responseLoading || onRunQuery
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
        [onRunQuery, responseLoading, runQuery, runSubquery]
    )

    return (
        <Shortcut
            name="SQLEditorRun"
            keybind={[keyBinds.run]}
            intent={showCancel ? 'Cancel query' : 'Run query'}
            interaction="click"
            scope={Scene.SQLEditor}
        >
            <LemonButton
                data-attr="sql-editor-run-button"
                onClick={() => {
                    if (onRunQuery) {
                        if (runQueryLoading) {
                            // Guard against double submission: one cancel request at a time.
                            if (onCancelQuery && !cancelQueryLoading) {
                                onCancelQuery()
                            }
                        } else {
                            onRunQuery()
                        }
                    } else if (responseLoading) {
                        cancelQuery()
                    } else {
                        runQuery()
                    }
                }}
                icon={showCancel ? <IconCancel /> : <IconPlayFilled color={iconColor} />}
                type="primary"
                size="small"
                tooltip={tooltipContent}
                sideAction={sideAction}
                loading={onRunQuery ? (onCancelQuery ? !!cancelQueryLoading : isRunning) : false}
                disabledReason={runQueryDisabledReason}
            >
                {showCancel ? 'Cancel' : 'Run'}
            </LemonButton>
        </Shortcut>
    )
}

const InternalQueryWindow = memo(function InternalQueryWindow({
    tabId,
    onShareTab,
}: {
    tabId: string
    onShareTab?: () => void
}): JSX.Element | null {
    const { finishedLoading } = useValues(sqlEditorLogic)

    if (finishedLoading) {
        return null
    }

    return <OutputPane tabId={tabId} onShareTab={onShareTab} />
})

function CollapsedConnectionSelector({ tabId, mode }: { tabId: string; mode?: SQLEditorMode }): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)

    if (!isDatabaseTreeCollapsed || (mode && mode !== SQLEditorMode.FullScene)) {
        return null
    }

    return <ConnectionSelector tabId={tabId} />
}
