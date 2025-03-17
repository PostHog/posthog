import { useValues } from 'kea'
import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
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
        case SessionRecordingSidebarTab.NETWORK_WATERFALL:
            return <NetworkView />
        default:
            return null
    }
}
