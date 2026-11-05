import { useValues } from 'kea'

import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillNewTicket } from './QuillNewTicket'
import { QuillRestoreTickets } from './QuillRestoreTickets'
import { QuillTicket } from './QuillTicket'
import { QuillTicketsList } from './QuillTicketsList'

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
