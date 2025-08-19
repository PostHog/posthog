import { useValues } from 'kea'

import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'

import { SessionRecordingSidebarTab } from '~/types'

import { PlayerSidebarOverviewTab } from './PlayerSidebarOverviewTab'
import { PlayerSidebarSessionSummaryTab } from './PlayerSidebarSessionSummaryTab'
import { playerSidebarLogic } from './playerSidebarLogic'

export function PlayerSidebarTab(): JSX.Element | null {
    const { activeTab } = useValues(playerSidebarLogic)

    switch (activeTab) {
        case SessionRecordingSidebarTab.OVERVIEW:
            return <PlayerSidebarOverviewTab />
        case SessionRecordingSidebarTab.INSPECTOR:
            return <PlayerInspector />
        case SessionRecordingSidebarTab.NETWORK_WATERFALL:
            return <NetworkView />
        case SessionRecordingSidebarTab.SESSION_SUMMARY:
            return <PlayerSidebarSessionSummaryTab />
        default:
            return null
    }
}
