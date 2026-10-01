import { useValues } from 'kea'
import { ReactNode } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { CONTEXT_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySessionActionItems } from './TodaySessionActionItems'
import { TodaySessionBulkActionItems } from './TodaySessionBulkActionItems'
import { TodaySessionSurface } from './todaySessionMenuLogic'
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
    const reportMenuOpen = useTodayPreviewMenuReport()
    // The selection lives in the sidebar, so only its rows offer the selection's actions.
    const bulk = surface === 'sidebar' && rightClickActsOnSelection(selectedSessionIds, target.sessionId)

    return (
        <ContextMenu onOpenChange={reportMenuOpen}>
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
