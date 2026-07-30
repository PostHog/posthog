import { useValues } from 'kea'

import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'

import { SessionRecordingSidebarTab } from '~/types'

import { PlayerSidebarLinkedIssuesTab } from './PlayerSidebarLinkedIssuesTab'
import { playerSidebarLogic } from './playerSidebarLogic'
import { PlayerSidebarOverviewTab } from './PlayerSidebarOverviewTab'
import { PlayerSidebarPersonRecordingsTab } from './PlayerSidebarPersonRecordingsTab'

export function PlayerSidebarTab(): JSX.Element | null {
    const { activeTab } = useValues(playerSidebarLogic)

    switch (activeTab) {
        case SessionRecordingSidebarTab.OVERVIEW:
            return <PlayerSidebarOverviewTab />
        case SessionRecordingSidebarTab.INSPECTOR:
            return <PlayerInspector />
        case SessionRecordingSidebarTab.NETWORK_WATERFALL:
            return <NetworkView />
        case SessionRecordingSidebarTab.LINKED_ISSUES:
            return <PlayerSidebarLinkedIssuesTab />
        case SessionRecordingSidebarTab.SESSIONS:
            return <PlayerSidebarPersonRecordingsTab />
        default:
            return null
    }
}
