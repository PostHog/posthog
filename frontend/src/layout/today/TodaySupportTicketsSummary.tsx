import { useActions, useValues } from 'kea'

import { SkeletonText } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { pluralize } from 'lib/utils/strings'

import { todayContextPanelLogic } from './todayContextPanelLogic'

export function TodaySupportTicketsSummary(): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { ticketsLoadState, ticketFilterCounts } = useValues(todayContextPanelLogic)
    const { loadTickets } = useActions(todayContextPanelLogic)

    // Not forced, so tickets that any tab fetched recently are reused instead of fetched again.
    useOnMountEffect(() => loadTickets())

    // Self-hosted instances have no tickets, so the row shows no count there.
    if (isCloudOrDev === false) {
        return null
    }
    if (ticketsLoadState === 'unknown') {
        return <SkeletonText lines={1} className="w-24" />
    }
    if (ticketsLoadState !== 'loaded') {
        return null
    }
    return (
        <span>
            {ticketFilterCounts.active > 0 ? pluralize(ticketFilterCounts.active, 'open ticket') : 'No open tickets'}
        </span>
    )
}
