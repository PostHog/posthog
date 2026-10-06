import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { CONTEXT_PARTS, SHEET_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySessionActionItems } from './TodaySessionActionItems'
import { useTodayArchiveShortcut } from './todaySessionArchiveShortcut'
import { TodayBulkSelection, TodaySessionBulkActionItems } from './TodaySessionBulkActionItems'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { rightClickActsOnSelection, sessionsLabel } from './todaySessionSelection'
import { TodaySheetMenu } from './TodaySheetMenu'
import { todayShellLogic } from './todayShellLogic'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodaySessionMenuTarget } from './todayWorkItems'

const BULK_DATA_ATTR_PREFIX: Record<TodaySessionSurface, string> = {
    sidebar: 'today-session-context-bulk',
    feed: 'today-space-feed-context-bulk',
}

interface TodaySessionContextMenuProps {
    target: TodaySessionMenuTarget
    surface: TodaySessionSurface
    /** The selection the row sits in. A right-click on a row inside it acts on the whole selection. */
    selection: TodayBulkSelection
    children: ReactNode
}

/** The session's actions on right-click, like PostHog Desktop. Its dialogs belong to the owner of `target.menuId`. */
export function TodaySessionContextMenu({
    target,
    surface,
    selection,
    children,
}: TodaySessionContextMenuProps): JSX.Element {
    const { requestArchive } = useActions(todaySessionMenuLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { spaceNames } = useValues(todaySpacesLogic)
    const { touchMenuOpened } = useActions(todaySpacesLogic)
    const reportMenuOpen = useTodayPreviewMenuReport()
    const [open, setOpen] = useState(false)
    const [sheetOpen, setSheetOpen] = useState(false)
    const setMenuOpen = (nextOpen: boolean): void => {
        setOpen(nextOpen)
        reportMenuOpen(nextOpen)
    }
    const bulk = rightClickActsOnSelection(selection.selectedSessionIds, target.sessionId)
    useTodayArchiveShortcut(open && !bulk, () => {
        setMenuOpen(false)
        requestArchive(target.sessionId, target.menuId, target.activeRunId)
    })

    if (phoneLayout) {
        const spaceName = target.spaceId ? spaceNames[target.spaceId] : null
        return (
            <>
                <ContextMenu
                    open={false}
                    onOpenChange={(next) => {
                        if (next) {
                            setSheetOpen(true)
                            touchMenuOpened(bulk ? 'bulk' : 'session')
                        }
                    }}
                >
                    <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
                </ContextMenu>
                <TodaySheetMenu
                    open={sheetOpen}
                    onOpenChange={setSheetOpen}
                    title={
                        bulk
                            ? `${sessionsLabel(selection.selectedSessionIds.length)} selected`
                            : target.title || 'Untitled session'
                    }
                    description={bulk ? undefined : (spaceName ?? undefined)}
                >
                    {bulk ? (
                        <TodaySessionBulkActionItems
                            parts={SHEET_PARTS}
                            selection={selection}
                            dataAttrPrefix={BULK_DATA_ATTR_PREFIX[surface]}
                        />
                    ) : (
                        <TodaySessionActionItems
                            parts={SHEET_PARTS}
                            target={target}
                            surface={surface}
                            dataAttrPrefix="today-session-sheet"
                        />
                    )}
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <ContextMenu open={open} onOpenChange={setMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
            {/* Wider for a selection, whose labels carry a count. */}
            <ContextMenuContent className={bulk ? 'w-64' : 'w-56'}>
                {bulk ? (
                    <TodaySessionBulkActionItems
                        parts={CONTEXT_PARTS}
                        selection={selection}
                        dataAttrPrefix={BULK_DATA_ATTR_PREFIX[surface]}
                    />
                ) : (
                    <TodaySessionActionItems
                        parts={CONTEXT_PARTS}
                        target={target}
                        surface={surface}
                        dataAttrPrefix="today-session-context"
                    />
                )}
            </ContextMenuContent>
        </ContextMenu>
    )
}
