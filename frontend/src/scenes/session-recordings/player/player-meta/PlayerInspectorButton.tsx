import { useActions, useValues } from 'kea'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import posthog from 'posthog-js'
import { SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'

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
            label="Explore"
            icon={<IconUnverifiedEvent />}
            active={sidebarOpen}
            onClick={(): void => {
                setSidebarOpen(!sidebarOpen)
                setTab(SessionRecordingSidebarTab.INSPECTOR)
                posthog.capture(!sidebarOpen ? 'opening player inspector' : 'closing player inspector', {})
            }}
            data-ph-capture-attribute-opening={!sidebarOpen}
            data-attr="open-player-inspector-button"
        />
    )
}
