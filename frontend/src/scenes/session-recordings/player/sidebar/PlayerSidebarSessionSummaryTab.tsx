import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

export function PlayerSidebarSessionSummaryTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { reportAISessionSummaryViewed } = useActions(sessionRecordingEventUsageLogic)

    useEffect(() => {
        reportAISessionSummaryViewed(logicProps.sessionRecordingId, 'tab')
    }, [logicProps.sessionRecordingId, reportAISessionSummaryViewed])

    return (
        <div className="flex flex-col overflow-auto bg-primary px-2 py-1 h-full">
            <PlayerSidebarSessionSummary />
        </div>
    )
}
