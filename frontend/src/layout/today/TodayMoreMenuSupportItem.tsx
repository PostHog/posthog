import { useActions, useValues } from 'kea'

import { DropdownMenuItem, SkeletonText } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { pluralize } from 'lib/utils/strings'

import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'

/**
 * The "More" menu's entry for the support panel, with the person's open ticket count.
 * The menu mounts this only while it is open, so it loads tickets once per opening and does not poll.
 */
export function TodayMoreMenuSupportItem(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { activeTab, docked, floatingOpen, ticketsLoadState, ticketFilterCounts } = useValues(todayContextPanelLogic)
    const { togglePanelTab, loadTickets } = useActions(todayContextPanelLogic)

    // Not forced, so tickets that any tab fetched recently are reused instead of fetched again.
    useOnMountEffect(() => loadTickets())

    const supportOpen = (docked || floatingOpen) && activeTab === SidePanelTab.Support

    return (
        <DropdownMenuItem
            onClick={() => {
                if (!supportOpen) {
                    togglePanelTab(SidePanelTab.Support)
                }
            }}
            description={
                // Self-hosted instances have no tickets, so the row shows no count there.
                isCloudOrDev === false ? null : ticketsLoadState === 'unknown' ? (
                    <SkeletonText lines={1} className="w-24" />
                ) : ticketsLoadState === 'loaded' ? (
                    ticketFilterCounts.active > 0 ? (
                        pluralize(ticketFilterCounts.active, 'open ticket')
                    ) : (
                        'No open tickets'
                    )
                ) : null
            }
            // pinned: matches the classic help menu's Support item, so autocapture data stays continuous
            data-attr="more-menu-support-button"
        >
            Support
        </DropdownMenuItem>
    )
}
