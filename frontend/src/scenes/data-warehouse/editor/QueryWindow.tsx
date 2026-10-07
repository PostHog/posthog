import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import posthog from 'posthog-js'
import { memo, useCallback, useMemo, useRef } from 'react'

import { IconDatabase, IconGear, IconInfo, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitlePanelButton'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { VimrcModal } from 'products/data_warehouse/frontend/shared/components/VimrcModal'
import { sqlEditorVimLogic } from 'products/data_warehouse/frontend/shared/logics/sqlEditorVimLogic'
import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { FixErrorButton } from './components/FixErrorButton'
import { ConnectionSelector } from './ConnectionSelector'
import { editorSizingLogic } from './editorSizingLogic'
import { applyExecuteSqlToolOutput, getExecuteSqlToolContext } from './maxSqlTool'
import { OutputPane } from './OutputPane'
import { QueryFiltersMenu } from './QueryFiltersMenu'
import { QueryPane } from './QueryPane'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { RunButton } from './RunButton'
import { sqlEditorLogic, tabModelPath } from './sqlEditorLogic'

const EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS = 150

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    tabId: string
    mode?: SQLEditorMode
    showDatabaseTree: boolean
    onShowDatabaseTree: () => void
    /** Which product embeds this editor. Only used to attribute analytics events to a host. */
    hostProduct?: ProductKey
    showQueryPanel?: boolean
    showOutputPanel?: boolean
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    /** With onRunQuery: flips the button to Cancel while runQueryLoading, mirroring the native cancel. */
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
    /** Drop the toolbar's run button, for hosts that offer the run affordance themselves
     * (a notebook code cell runs from the cell's top row). Cmd+Enter still runs. */
    hideRunButton?: boolean
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
    hostProduct,
    showQueryPanel = true,
    showOutputPanel = true,
    onRunQuery,
    runQueryLoading,
    runQueryDisabledReason,
    runQueryTooltip,
    onCancelQuery,
    cancelQueryLoading,
    hideRunButton,
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
        selectedConnectionSupportsHogQL,
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

    const { setSuggestedQueryInput, reportAIQueryPromptOpen, fixIndexUsageWithAI } = useActions(logic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { vimModeEnabled, vimrc, editorSettingsMenuKey } = useValues(sqlEditorVimLogic)
    const { setVimModeEnabled, openVimrcModal, setEditorSettingsMenuOpen } = useActions(sqlEditorVimLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    // Raw-only connections are forced to raw SQL mode — no toggle to show.
    const canSendRawQuery = !!selectedConnectionId && selectedConnectionSupportsHogQL
    const debouncedMaxToolQueryInput = useDebouncedValue(queryInput, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const debouncedMaxToolSourceQuery = useDebouncedValue(sourceQuery, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const executeSqlToolStateRef = useRef({ queryInput, sourceQuery })
    executeSqlToolStateRef.current = { queryInput, sourceQuery }
    const executeSqlToolContext = useMemo(
        () => getExecuteSqlToolContext(debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery),
        [debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery]
    )

    const attachedContextItems = useMemo(
        () => [
            { type: 'sql_editor_state' as const, value: JSON.stringify(executeSqlToolContext), label: 'Current query' },
        ],
        [executeSqlToolContext]
    )
    useAttachedContext(attachedContextItems, { active: showQueryPanel })

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
    // Sandbox-runtime apply-back for the same tool the legacy MaxTool callback above handles. Reuses
    // that callback verbatim so the diff-mode gate and filters handling stay shared with legacy.
    useMcpToolApplyBack({
        tools: ['execute-sql'],
        targetKey: `sql:${tabId}`,
        active: showQueryPanel,
        onApply: (_event, { innerInput }) => {
            if (!showQueryPanel || !innerInput) {
                return
            }
            handleExecuteSqlToolOutput(innerInput)
        },
    })
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
                              checked={vimModeEnabled}
                              onChange={setVimModeEnabled}
                              label="Vim mode"
                              size="small"
                              fullWidth
                              data-attr="sql-editor-vim-toggle"
                          />
                      ),
                  },
                  ...(vimModeEnabled
                      ? [
                            {
                                label: 'Edit vimrc',
                                onClick: () => openVimrcModal(codeEditorKey),
                                size: 'small' as const,
                                'data-attr': 'sql-editor-vimrc-edit',
                            },
                        ]
                      : []),
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
                            mode={mode}
                            hostProduct={hostProduct}
                        />
                        {hideRunButton ? null : (
                            <RunButton
                                onRunQuery={onRunQuery}
                                runQueryLoading={runQueryLoading}
                                runQueryDisabledReason={runQueryDisabledReason}
                                runQueryTooltip={runQueryTooltip}
                                onCancelQuery={onCancelQuery}
                                cancelQueryLoading={cancelQueryLoading}
                            />
                        )}
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
                            <LemonMenu
                                items={editorSettingsItems}
                                closeOnClickInside={false}
                                placement="bottom-end"
                                visible={editorSettingsMenuKey === codeEditorKey}
                                onVisibilityChange={(open) => setEditorSettingsMenuOpen(codeEditorKey, open)}
                            >
                                <LemonButton
                                    icon={<IconGear />}
                                    type="secondary"
                                    size="small"
                                    tooltip="Editor settings"
                                    data-attr="sql-editor-settings-toggle"
                                />
                            </LemonMenu>
                        ) : null}
                        {vimModeFeatureEnabled ? <VimrcModal editorKey={codeEditorKey} /> : null}
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
                    editorVimModeEnabled={vimModeFeatureEnabled && vimModeEnabled}
                    editorVimrc={vimrc}
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
                        // Set here rather than only where the tab's Monaco model is created: an editor
                        // that mounts against an existing model never runs that path, and would then
                        // ask for metadata without the index report.
                        indexUsage: true,
                        onFixWithAI: (prompt) => fixIndexUsageWithAI(prompt),
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

            {showOutputPanel ? <InternalQueryWindow tabId={tabId} biMode={false} onShareTab={onShareTab} /> : null}
        </div>
    )
}

function ExpandDatabaseTreeButton({
    showDatabaseTree,
    onShowDatabaseTree,
    mode,
    hostProduct,
}: {
    showDatabaseTree: boolean
    onShowDatabaseTree: () => void
    mode?: SQLEditorMode
    hostProduct?: ProductKey
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
                // This button only ever opens the panel, because it renders nothing once the panel
                // is open and expanded. So every click is one open, and no close is counted here.
                posthog.capture('sql-editor-schema-panel-opened', {
                    mode: mode ?? SQLEditorMode.FullScene,
                    host_product: hostProduct ?? null,
                    // False when the panel was open before and the user collapsed it by dragging.
                    is_first_open: !showDatabaseTree,
                })
                if (!showDatabaseTree) {
                    onShowDatabaseTree()
                    return
                }
                toggleDatabaseTreeCollapsed()
            }}
        />
    )
}

const InternalQueryWindow = memo(function InternalQueryWindow({
    tabId,
    biMode,
    onShareTab,
}: {
    tabId: string
    biMode: boolean
    onShareTab?: () => void
}): JSX.Element | null {
    const { finishedLoading } = useValues(sqlEditorLogic)

    if (finishedLoading) {
        return null
    }

    return <OutputPane tabId={tabId} biMode={biMode} onShareTab={onShareTab} />
})

function CollapsedConnectionSelector({ tabId, mode }: { tabId: string; mode?: SQLEditorMode }): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)

    if (!isDatabaseTreeCollapsed || (mode && mode !== SQLEditorMode.FullScene)) {
        return null
    }

    return <ConnectionSelector tabId={tabId} />
}
