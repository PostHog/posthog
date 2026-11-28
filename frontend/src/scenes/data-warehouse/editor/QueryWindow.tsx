import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import type { editor as importedEditor } from 'monaco-editor'
import posthog from 'posthog-js'
import { memo } from 'react'

import { IconDatabase, IconGear, IconInfo, IconPlus, IconSidebarClose } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { urls } from 'scenes/urls'

import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitlePanelButton'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { VimrcModal } from 'products/data_warehouse/frontend/shared/components/VimrcModal'
import { sqlEditorVimLogic } from 'products/data_warehouse/frontend/shared/logics/sqlEditorVimLogic'
import { viewEngine } from 'products/data_warehouse/frontend/shared/viewEngine'

import { FixErrorButton } from './components/FixErrorButton'
import { ConnectionSelector } from './ConnectionSelector'
import { editorSizingLogic } from './editorSizingLogic'
import { OutputPane } from './OutputPane'
import { QueryFiltersMenu } from './QueryFiltersMenu'
import { QueryPane } from './QueryPane'
import { QueryPlaceholdersMenu } from './QueryPlaceholdersMenu'
import { QueryVariablesMenu } from './QueryVariablesMenu'
import { RunButton } from './RunButton'
import { sqlEditorLogic } from './sqlEditorLogic'
import { useExecuteSqlToolBridge } from './useExecuteSqlToolBridge'
import { useQueryPaneProps } from './useQueryPaneProps'

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
    hideVariables?: boolean
    hideFilters?: boolean
    hideAiTools?: boolean
    hideConnectionSelector?: boolean
    captureQueryTelemetry?: boolean
    showOpenInSqlEditor?: boolean
    /** False removes the button that expands the schema panel. Defaults to true. */
    canExpandDatabaseTree?: boolean
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
    hideVariables,
    hideFilters,
    hideAiTools,
    hideConnectionSelector,
    captureQueryTelemetry,
    showOpenInSqlEditor,
    canExpandDatabaseTree = true,
}: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`
    const logic = sqlEditorLogic({ tabId, captureQueryTelemetry })

    const {
        sourceQuery,
        editingView,
        selectedConnectionId,
        sendRawQueryEnabled,
        selectedConnectionSupportsHogQL,
        singleStatementDisabledReason,
    } = useValues(logic)

    const { setSendRawQuery, openMaterializationModal } = useActions(logic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { vimModeEnabled, editorSettingsMenuKey } = useValues(sqlEditorVimLogic)
    const { setVimModeEnabled, openVimrcModal, setEditorSettingsMenuOpen } = useActions(sqlEditorVimLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    // Raw-only connections are forced to raw SQL mode — no toggle to show.
    const canSendRawQuery =
        sourceQuery.source.executionTarget === 'managed_trino' ||
        (!!selectedConnectionId && selectedConnectionSupportsHogQL)
    const executeSqlMaxToolProps = useExecuteSqlToolBridge(tabId, showQueryPanel)
    const sendRawQueryLabel = (
        <span className="inline-flex items-center gap-1">
            <span>Send raw query</span>
            <Tooltip title="Send the query directly to the selected connection without translating it through HogQL first. This is an escape hatch for SQL syntax that HogQL does not yet support. Your query may be logged to improve the service.">
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

    const queryPaneProps = useQueryPaneProps({
        tabId,
        codeEditorKey,
        onSetMonacoAndEditor,
        onRunQuery,
        runQueryLoading,
        autoFocusQueryPane,
        captureQueryTelemetry,
    })

    return (
        <div className="flex grow flex-col overflow-hidden">
            {showQueryPanel ? (
                <div
                    className={cn(
                        'flex flex-row flex-wrap gap-y-1 justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b border-t py-1',
                        isDatabaseTreeCollapsed || mode !== SQLEditorMode.FullScene ? '' : 'rounded-tl-lg'
                    )}
                >
                    <div className="flex flex-wrap items-center gap-2">
                        {canExpandDatabaseTree ? (
                            <ExpandDatabaseTreeButton
                                showDatabaseTree={showDatabaseTree}
                                onShowDatabaseTree={onShowDatabaseTree}
                                mode={mode}
                                hostProduct={hostProduct}
                            />
                        ) : null}
                        {hideRunButton ? null : (
                            <RunButton
                                onRunQuery={onRunQuery}
                                runQueryLoading={runQueryLoading}
                                runQueryDisabledReason={
                                    runQueryDisabledReason ?? singleStatementDisabledReason ?? undefined
                                }
                                runQueryTooltip={runQueryTooltip}
                                onCancelQuery={onCancelQuery}
                                cancelQueryLoading={cancelQueryLoading}
                            />
                        )}
                        {!hideConnectionSelector && <CollapsedConnectionSelector tabId={tabId} mode={mode} />}
                        {mode === SQLEditorMode.FullScene ? (
                            <LemonButton
                                icon={<IconPlus />}
                                type="secondary"
                                size="small"
                                // An explicit empty query skips the recovery of this tab's unsaved working copy.
                                to={combineUrl(urls.sqlEditor(), { open_query: '' }).url}
                                targetBlank
                                tooltip="Open a new SQL editor in a new browser tab"
                                aria-label="Open a new SQL editor in a new browser tab"
                                data-attr="sql-editor-new-browser-tab"
                            />
                        ) : null}
                        <LemonDivider vertical />
                        {!hideVariables ? (
                            <QueryVariablesMenu
                                disabledReason={editingView ? 'Variables are not allowed in views.' : undefined}
                            />
                        ) : null}
                        {!hideFilters ? <QueryFiltersMenu /> : null}
                        <QueryPlaceholdersMenu />
                        {editingView && mode !== SQLEditorMode.Embedded ? (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconDatabase />}
                                    onClick={() => openMaterializationModal(editingView)}
                                    disabledReason={
                                        viewEngine(editingView).capabilities.materialize.reason ?? undefined
                                    }
                                    data-attr="sql-editor-materialization-button"
                                >
                                    Materialization
                                </LemonButton>
                            </AccessControlAction>
                        ) : null}
                    </div>

                    <div className="ml-auto flex items-center gap-2">
                        {showOpenInSqlEditor ? <OpenInSqlEditorButton /> : null}
                        {hideAiTools ? null : <FixErrorButton type="secondary" size="small" source="action-bar" />}
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
                        {mode === SQLEditorMode.Embedded && !hideAiTools && (
                            <SceneTitlePanelButton
                                buttonClassName="size-[26px]"
                                maxToolProps={executeSqlMaxToolProps}
                            />
                        )}
                    </div>
                </div>
            ) : null}

            {showQueryPanel ? <QueryPane {...queryPaneProps} constrainHeight={showOutputPanel} /> : null}

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

function OpenInSqlEditorButton(): JSX.Element {
    const { editingView, queryInput, hasEditorChanges } = useValues(sqlEditorLogic)

    // Unsaved edits travel with the link, so the view opens in the SQL editor with them applied and not saved.
    return (
        <LemonButton
            type="secondary"
            size="small"
            to={urls.sqlEditor({
                view_id: editingView?.id,
                query: !editingView || hasEditorChanges ? (queryInput ?? '') : undefined,
            })}
            data-attr="sql-editor-open-in-sql-editor"
        >
            Open in SQL editor
        </LemonButton>
    )
}

function CollapsedConnectionSelector({ tabId, mode }: { tabId: string; mode?: SQLEditorMode }): JSX.Element | null {
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)

    if (!isDatabaseTreeCollapsed || (mode && mode !== SQLEditorMode.FullScene)) {
        return null
    }

    return <ConnectionSelector tabId={tabId} />
}
