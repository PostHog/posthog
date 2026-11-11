import { useValues } from 'kea'

import { TodaySessionArchiveDialog } from './TodaySessionArchiveDialog'
import { TodaySessionHandoffDialog } from './TodaySessionHandoffDialog'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionMenuTarget } from './todayWorkItems'

/** The dialogs a session's actions open. The row or card that owns `target.menuId` renders them, so they outlive the menu. */
export function TodaySessionDialogs({ target }: { target: TodaySessionMenuTarget }): JSX.Element {
    const { handoffMenuId, archiveConfirmMenuId } = useValues(todaySessionMenuLogic)
    return (
        <>
            {target.canHandOff && handoffMenuId === target.menuId && (
                <TodaySessionHandoffDialog sessionId={target.sessionId} />
            )}
            {target.activeRunId && archiveConfirmMenuId === target.menuId && (
                <TodaySessionArchiveDialog
                    sessionId={target.sessionId}
                    title={target.title}
                    runId={target.activeRunId}
                />
            )}
        </>
    )
}
