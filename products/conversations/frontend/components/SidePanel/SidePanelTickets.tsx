import { useValues } from 'kea'

import { NewTicket } from './NewTicket'
import { Ticket } from './Ticket'
import { TicketsList } from './TicketsList'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function SidePanelTickets(): JSX.Element {
    const { view } = useValues(sidepanelTicketsLogic)

    return (
        <div>
            {view === 'list' && <TicketsList />}
            {view === 'ticket' && <Ticket />}
            {view === 'new' && <NewTicket />}
        </div>
    )
}
