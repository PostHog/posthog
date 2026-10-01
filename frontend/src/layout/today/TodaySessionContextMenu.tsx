import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { CONTEXT_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySessionActionItems } from './TodaySessionActionItems'
import { useTodayArchiveShortcut } from './todaySessionArchiveShortcut'
import { TodaySessionBulkActionItems } from './TodaySessionBulkActionItems'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { rightClickActsOnSelection } from './todaySessionSelection'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { TodaySessionMenuTarget } from './todayWorkItems'

interface TodaySessionContextMenuProps {
    target: TodaySessionMenuTarget
    surface: TodaySessionSurface
    children: ReactNode
}

/** The session's actions on right-click, like PostHog Desktop. Its dialogs belong to the owner of `target.menuId`. */
export function TodaySessionContextMenu({ target, surface, children }: TodaySessionContextMenuProps): JSX.Element {
    const { selectedSessionIds } = useValues(todaySessionSelectionLogic)
    const { requestArchive } = useActions(todaySessionMenuLogic)
    const reportMenuOpen = useTodayPreviewMenuReport()
    const [open, setOpen] = useState(false)
    const setMenuOpen = (nextOpen: boolean): void => {
        setOpen(nextOpen)
        reportMenuOpen(nextOpen)
    }
    // The selection lives in the sidebar, so only its rows offer the selection's actions.
    const bulk = surface === 'sidebar' && rightClickActsOnSelection(selectedSessionIds, target.sessionId)
    useTodayArchiveShortcut(open && !bulk, () => {
        setMenuOpen(false)
        requestArchive(target.sessionId, target.menuId, target.activeRunId)
    })

    return (
        <ContextMenu open={open} onOpenChange={setMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
            {/* Wider for a selection, whose labels carry a count. */}
            <ContextMenuContent className={bulk ? 'w-64' : 'w-56'}>
                {bulk ? (
                    <TodaySessionBulkActionItems parts={CONTEXT_PARTS} dataAttrPrefix="today-session-context-bulk" />
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
