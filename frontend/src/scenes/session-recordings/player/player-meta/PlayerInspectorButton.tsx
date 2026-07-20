import { useActions, useValues } from 'kea'

import { SettingsToggle } from 'lib/components/PanelSettings/PanelSettings'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'

import { SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { playerSidebarLogic } from '../sidebar/playerSidebarLogic'

export function PlayerInspectorButton(): JSX.Element {
    const { setTab } = useActions(playerSidebarLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)
    const { sidebarOpen } = useValues(playerSettingsLogic)

    return (
        <SettingsToggle
            title="View all activities from this session, including events, console logs, network requests, and an overview. Explore what happened in detail."
            label="Activity"
            icon={<IconUnverifiedEvent />}
            active={sidebarOpen}
            onClick={(): void => {
                setSidebarOpen(!sidebarOpen)
                setTab(SessionRecordingSidebarTab.INSPECTOR)
            }}
            data-ph-capture-attribute-opening={!sidebarOpen}
            data-attr="open-player-inspector-button"
        />
    )
}
