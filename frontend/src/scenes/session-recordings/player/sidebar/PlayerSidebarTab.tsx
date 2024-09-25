import { useValues } from 'kea'

import { SessionRecordingSidebarTab } from '~/types'

import { PlayerInspectorControls } from '../inspector/PlayerInspectorControls'
import { PlayerInspectorList } from '../inspector/PlayerInspectorList'
import { PlayerSidebarDebuggerTab } from './PlayerSidebarDebuggerTab'
import { playerSidebarLogic } from './playerSidebarLogic'
import { PlayerSidebarPersonTab } from './PlayerSidebarPersonTab'

export function PlayerSidebarTab(): JSX.Element | null {
    const { activeTab } = useValues(playerSidebarLogic)

    switch (activeTab) {
        case SessionRecordingSidebarTab.OVERVIEW:
            return <PlayerSidebarPersonTab />
        case SessionRecordingSidebarTab.INSPECTOR:
            return (
                <>
                    <PlayerInspectorControls />
                    <PlayerInspectorList />
                </>
            )
        case SessionRecordingSidebarTab.DEBUGGER:
            return <PlayerSidebarDebuggerTab />
        default:
            return null
    }
}
