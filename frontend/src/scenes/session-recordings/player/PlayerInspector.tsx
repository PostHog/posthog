/**
 * @fileoverview PlayerInspector component is a button that opens the inspector sidebar
 */
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'

import { SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from './playerSettingsLogic'
import { playerSidebarLogic } from './sidebar/playerSidebarLogic'

export function PlayerInspector(): JSX.Element {
    const { setTab } = useActions(playerSidebarLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)

    const handleClick = (): void => {
        setSidebarOpen(true)
        setTab(SessionRecordingSidebarTab.INSPECTOR)
    }

    return (
        <LemonButton
            size="xsmall"
            tooltip="View all activities from this session, including events, console logs, network requests, and an overview. Explore what happened in detail."
            icon={<IconUnverifiedEvent />}
            onClick={handleClick}
        >
            Activity
        </LemonButton>
    )
}
