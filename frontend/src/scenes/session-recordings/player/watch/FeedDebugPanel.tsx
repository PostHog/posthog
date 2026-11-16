import { useActions, useValues } from 'kea'
import { createContext, useContext } from 'react'
import { createPortal } from 'react-dom'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarTab'
import { useLinkedIssuesAvailable } from 'scenes/session-recordings/player/sidebar/useLinkedIssuesAvailable'

import { SessionRecordingSidebarTab } from '~/types'

import { DebugTabBar, debugTabKeys } from './DebugTabBar'

/** The element in the feed layout's list column that the player's debug view renders into. */
export const FeedDebugSlotContext = createContext<HTMLElement | null>(null)

/** Portals from the player so the tabs keep the player's logics while sitting where the recording list is. */
export function FeedDebugPanel(): JSX.Element | null {
    const slot = useContext(FeedDebugSlotContext)
    const { setDebugMode } = useActions(playerSettingsLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const debugTabs = debugTabKeys(useLinkedIssuesAvailable())
    const debugTab = debugTabs.includes(activeTab) ? activeTab : SessionRecordingSidebarTab.INSPECTOR

    if (!slot) {
        return null
    }

    return createPortal(
        <div
            data-not-quill
            className="flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden rounded border bg-surface-primary"
            data-attr="feed-debug-panel"
        >
            <DebugTabBar tabs={debugTabs} activeTab={debugTab} onChange={setTab}>
                <Button
                    size="icon"
                    onClick={() => setDebugMode(false)}
                    tooltip="Close and show the recording list"
                    aria-label="Close and show the recording list"
                    className="rounded-none"
                    data-attr="feed-debug-close"
                >
                    <IconX />
                </Button>
            </DebugTabBar>
            <div className="flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden">
                <PlayerSidebarTab tab={debugTab} />
            </div>
        </div>,
        slot
    )
}
