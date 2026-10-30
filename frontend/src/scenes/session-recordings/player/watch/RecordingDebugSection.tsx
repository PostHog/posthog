import { useActions, useValues } from 'kea'

import { IconSidePanel } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { SessionRecordingSidebarTab } from '~/types'

import { DEBUG_TAB_KEYS, DebugTabBar } from './DebugTabBar'

export function RecordingDebugSection(): JSX.Element {
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const { setWatchDebugDock } = useActions(playerSettingsLogic)
    const tab = DEBUG_TAB_KEYS.includes(activeTab) ? activeTab : SessionRecordingSidebarTab.INSPECTOR

    return (
        <div
            className="flex flex-col border rounded bg-surface-primary overflow-hidden h-[calc(45cqh-1.5rem)] min-h-48"
            data-attr="watch-panel-debug"
        >
            <DebugTabBar tabs={DEBUG_TAB_KEYS} activeTab={tab} onChange={setTab}>
                <LemonButton
                    size="small"
                    icon={<IconSidePanel />}
                    onClick={() => setWatchDebugDock('right')}
                    tooltip="Dock to right"
                    aria-label="Dock to right"
                    className="rounded-none"
                    data-attr="player-sidebar-dock-toggle"
                />
            </DebugTabBar>
            <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
                {tab === SessionRecordingSidebarTab.NETWORK_WATERFALL ? <NetworkView /> : <PlayerInspector />}
            </div>
        </div>
    )
}
