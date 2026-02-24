import { useValues } from 'kea'

import { NewTicket } from './NewTicket'
import { RestoreTickets } from './RestoreTickets'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'
import { Ticket } from './Ticket'
import { TicketsList } from './TicketsList'

export function SidePanelTickets(): JSX.Element {
    const { view } = useValues(sidepanelTicketsLogic)

    return (
        <div>
            {view === 'list' && <TicketsList />}
            {view === 'ticket' && <Ticket />}
            {view === 'new' && <NewTicket />}
            {view === 'restore' && <RestoreTickets />}
        </div>
    )
}
