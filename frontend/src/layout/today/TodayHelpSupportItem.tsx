import { useActions, useValues } from 'kea'

import { DropdownMenuItem } from '@posthog/quill'

import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'
import { TodaySupportTicketsSummary } from './TodaySupportTicketsSummary'

/**
 * The help items' entry for the support panel, with the person's open ticket count.
 * The menu mounts this only while it is open, so it loads tickets once per opening and does not poll.
 */
export function TodayHelpSupportItem(): JSX.Element {
    const { activeTab, docked, floatingOpen } = useValues(todayContextPanelLogic)
    const { togglePanelTab } = useActions(todayContextPanelLogic)

    const supportOpen = (docked || floatingOpen) && activeTab === SidePanelTab.Support

    return (
        <DropdownMenuItem
            onClick={() => {
                if (!supportOpen) {
                    togglePanelTab(SidePanelTab.Support)
                }
            }}
            description={<TodaySupportTicketsSummary />}
            // pinned: matches the classic help menu's Support item, so autocapture data stays continuous
            data-attr="more-menu-support-button"
        >
            Support
        </DropdownMenuItem>
    )
}
