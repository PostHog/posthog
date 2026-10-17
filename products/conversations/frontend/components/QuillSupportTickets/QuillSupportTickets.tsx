import { useValues } from 'kea'

import { QuillNewTicket } from '../QuillNewTicket/QuillNewTicket'
import { QuillRestoreTickets } from '../QuillRestoreTickets/QuillRestoreTickets'
import { QuillTicket } from '../QuillTicket/QuillTicket'
import { QuillTicketsList } from '../QuillTicketsList/QuillTicketsList'
import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'

export function QuillSupportTickets(): JSX.Element {
    const { view, newTicketDraftRevision } = useValues(sidepanelTicketsLogic)
    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    return (
        <>
            {view === 'list' && <QuillTicketsList />}
            {view === 'ticket' && <QuillTicket />}
            {/* Keyed on the draft revision, so a prefill injected while the composer is open remounts the editor. */}
            {view === 'new' && <QuillNewTicket key={newTicketDraftRevision} />}
            {view === 'restore' && !hasIdentityMode && <QuillRestoreTickets />}
        </>
    )
}
