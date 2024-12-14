import { useValues } from 'kea'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionRecordingSidebarTab } from '~/types'

import { PlayerSidebarDebuggerTab } from './PlayerSidebarDebuggerTab'
import { playerSidebarLogic } from './playerSidebarLogic'
import { PlayerSidebarOverviewTab } from './PlayerSidebarOverviewTab'

export function PlayerSidebarTab(): JSX.Element | null {
    const { activeTab } = useValues(playerSidebarLogic)
    // this tab is mounted within a component that has bound this logic
    // the inspector is not always, and we pass the values in
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    switch (activeTab) {
        case SessionRecordingSidebarTab.OVERVIEW:
            return <PlayerSidebarOverviewTab />
        case SessionRecordingSidebarTab.INSPECTOR:
            return <PlayerInspector {...logicProps} />
        case SessionRecordingSidebarTab.DEBUGGER:
            return <PlayerSidebarDebuggerTab />
        default:
            return null
    }
}
