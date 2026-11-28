import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconEllipsis, IconExternal } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { urls } from 'scenes/urls'

import { sqlEditorVimLogic } from 'products/data_warehouse/frontend/shared/logics/sqlEditorVimLogic'

import { SqlEditorInspectorSide, SqlEditorResultsPlacement, SQL_EDITOR_INSPECTOR_TABS } from './sqlEditorLayout'
import { sqlEditorLayoutLogic } from './sqlEditorLayoutLogic'
import { INSPECTOR_TAB_LABELS } from './sqlEditorWorkspaceCopy'

/**
 * The toolbar's overflow menu. It holds what fewer than 4% of editor users reach for, plus the
 * layout settings that make the workspace rearrangeable.
 */
export function QuillWorkspaceMoreMenu({ codeEditorKey }: { codeEditorKey: string }): JSX.Element {
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { vimModeEnabled } = useValues(sqlEditorVimLogic)
    const { setVimModeEnabled, openVimrcModal } = useActions(sqlEditorVimLogic)
    const { sourceQuery, selectedConnectionId, selectedConnectionSupportsHogQL, sendRawQueryEnabled } =
        useValues(sqlEditorLogic)
    const { setSendRawQuery } = useActions(sqlEditorLogic)
    const { layout, isCustomized } = useValues(sqlEditorLayoutLogic)
    const { setInspectorSide, setResultsPlacement, setInspectorTabVisible, resetLayout } =
        useActions(sqlEditorLayoutLogic)

    // Raw-only connections are forced to raw SQL mode, so there is no toggle to show for them.
    const canSendRawQuery =
        sourceQuery.source.executionTarget === 'managed_trino' ||
        (!!selectedConnectionId && selectedConnectionSupportsHogQL)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button size="icon" aria-label="More" tooltip="More" data-attr="sql-editor-more-menu" />}
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    <DropdownMenuItem
                        // An explicit empty query skips the recovery of this tab's unsaved working copy.
                        onClick={() =>
                            window.open(combineUrl(urls.sqlEditor(), { open_query: '' }).url, '_blank', 'noopener')
                        }
                        data-attr="sql-editor-new-browser-tab"
                    >
                        New query in a browser tab
                        <IconExternal className="ms-auto" />
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                {vimModeFeatureEnabled || canSendRawQuery ? (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Editor</DropdownMenuLabel>
                            {vimModeFeatureEnabled ? (
                                <DropdownMenuCheckboxItem
                                    checked={vimModeEnabled}
                                    onCheckedChange={(checked) => setVimModeEnabled(checked)}
                                    closeOnClick={false}
                                    data-attr="sql-editor-vim-toggle"
                                >
                                    Vim mode
                                </DropdownMenuCheckboxItem>
                            ) : null}
                            {vimModeFeatureEnabled && vimModeEnabled ? (
                                <DropdownMenuItem
                                    inset
                                    onClick={() => openVimrcModal(codeEditorKey)}
                                    data-attr="sql-editor-vimrc-edit"
                                >
                                    Edit vimrc…
                                </DropdownMenuItem>
                            ) : null}
                            {canSendRawQuery ? (
                                <DropdownMenuCheckboxItem
                                    checked={sendRawQueryEnabled}
                                    onCheckedChange={(checked) => setSendRawQuery(checked)}
                                    closeOnClick={false}
                                    tooltip="Sends the query to the connection as written, without translating it through HogQL. Use it for SQL that HogQL doesn't support yet. Your query may be logged to improve the service."
                                    data-attr="sql-editor-send-raw-query-toggle"
                                >
                                    Send raw query
                                </DropdownMenuCheckboxItem>
                            ) : null}
                        </DropdownMenuGroup>
                    </>
                ) : null}
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="sql-editor-layout-menu">Layout</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Side panel</DropdownMenuLabel>
                                <DropdownMenuRadioGroup
                                    value={layout.inspector.side}
                                    onValueChange={(side) => setInspectorSide(side as SqlEditorInspectorSide)}
                                >
                                    <DropdownMenuRadioItem value="right" closeOnClick={false}>
                                        On the right
                                    </DropdownMenuRadioItem>
                                    <DropdownMenuRadioItem value="left" closeOnClick={false}>
                                        On the left
                                    </DropdownMenuRadioItem>
                                </DropdownMenuRadioGroup>
                            </DropdownMenuGroup>
                            <DropdownMenuSeparator />
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Side panel tabs</DropdownMenuLabel>
                                {SQL_EDITOR_INSPECTOR_TABS.map((tab) => (
                                    <DropdownMenuCheckboxItem
                                        key={tab}
                                        checked={layout.inspector.tabs.includes(tab)}
                                        onCheckedChange={(checked) => setInspectorTabVisible(tab, checked)}
                                        disabledReason={
                                            layout.inspector.tabs.length === 1 && layout.inspector.tabs[0] === tab
                                                ? 'The side panel needs at least one tab'
                                                : undefined
                                        }
                                        closeOnClick={false}
                                    >
                                        {INSPECTOR_TAB_LABELS[tab]}
                                    </DropdownMenuCheckboxItem>
                                ))}
                            </DropdownMenuGroup>
                            <DropdownMenuSeparator />
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Results</DropdownMenuLabel>
                                <DropdownMenuRadioGroup
                                    value={layout.results.placement}
                                    onValueChange={(placement) =>
                                        setResultsPlacement(placement as SqlEditorResultsPlacement)
                                    }
                                >
                                    <DropdownMenuRadioItem value="below" closeOnClick={false}>
                                        Below the query
                                    </DropdownMenuRadioItem>
                                    <DropdownMenuRadioItem value="beside" closeOnClick={false}>
                                        Beside the query
                                    </DropdownMenuRadioItem>
                                </DropdownMenuRadioGroup>
                            </DropdownMenuGroup>
                            {isCustomized ? (
                                <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuGroup>
                                        <DropdownMenuItem onClick={() => resetLayout()}>Reset layout</DropdownMenuItem>
                                    </DropdownMenuGroup>
                                </>
                            ) : null}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
