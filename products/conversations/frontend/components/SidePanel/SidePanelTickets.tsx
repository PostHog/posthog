import { useValues } from 'kea'

import { NewTicket } from './NewTicket'
import { RestoreTickets } from './RestoreTickets'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'
import { Ticket } from './Ticket'
import { TicketsList } from './TicketsList'

export function SidePanelTickets(): JSX.Element {
    const { view, composerRevision } = useValues(sidepanelTicketsLogic)
    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    return (
        <div>
            {view === 'list' && <TicketsList />}
            {view === 'ticket' && <Ticket />}
            {/* Key on the composer revision so a prefill or discard while the composer is already open
                remounts the editor (it only reads initial content at creation) */}
            {view === 'new' && <NewTicket key={composerRevision} />}
            {view === 'restore' && !hasIdentityMode && <RestoreTickets />}
        </div>
    )
}
