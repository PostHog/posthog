import { useActions, useValues } from 'kea'

import { PinToggleButton } from './sidebar/PinToggleButton'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

/** The pin after a chat's title. It pins the chat to the Chats pane, as the row menu's Pin does. */
export function TodaySessionPinButton({ sessionId, name }: { sessionId: string; name: string }): JSX.Element {
    const { pinnedItems, pinnedTasksLoading } = useValues(todaySpacesLogic)
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { setSessionPinned } = useActions(todaySessionMenuLogic)
    const pinned = pinnedItems.some((item) => item.id === sessionId)
    return (
        <PinToggleButton
            pinned={pinned}
            name={name}
            busy={pinnedTasksLoading || pendingSessionIds.includes(sessionId)}
            onToggle={() => setSessionPinned(sessionId, !pinned)}
            size="icon-sm"
            dataAttr="task-title-pin"
        />
    )
}
