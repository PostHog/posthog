import { useValues } from 'kea'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'

import { SessionRecordingSidebarTab } from '~/types'

import { PlayerSidebarDebuggerTab } from './PlayerSidebarDebuggerTab'
import { playerSidebarLogic } from './playerSidebarLogic'
import { PlayerSidebarOverviewTab } from './PlayerSidebarOverviewTab'

export function PlayerSidebarTab(): JSX.Element | null {
    const { activeTab } = useValues(playerSidebarLogic)

    switch (activeTab) {
        case SessionRecordingSidebarTab.OVERVIEW:
            return <PlayerSidebarOverviewTab />
        case SessionRecordingSidebarTab.INSPECTOR:
            return <PlayerInspector />
        case SessionRecordingSidebarTab.DEBUGGER:
            return <PlayerSidebarDebuggerTab />
        default:
            return null
    }
}
