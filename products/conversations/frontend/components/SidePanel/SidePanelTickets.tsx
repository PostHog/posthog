import { useValues } from 'kea'

import { NewTicket } from './NewTicket'
import { RestoreTickets } from './RestoreTickets'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'
import { Ticket } from './Ticket'
import { TicketsList } from './TicketsList'

export function SidePanelTickets(): JSX.Element {
    const { view } = useValues(sidepanelTicketsLogic)
    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    return (
        <div>
            {view === 'list' && <TicketsList />}
            {view === 'ticket' && <Ticket />}
            {view === 'new' && <NewTicket />}
            {view === 'restore' && !hasIdentityMode && <RestoreTickets />}
        </div>
    )
}
