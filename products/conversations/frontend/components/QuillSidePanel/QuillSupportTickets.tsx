import { useValues } from 'kea'

import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillNewTicket } from './QuillNewTicket'
import { QuillRestoreTickets } from './QuillRestoreTickets'
import { QuillTicket } from './QuillTicket'
import { QuillTicketsList } from './QuillTicketsList'

export function QuillSupportTickets(): JSX.Element {
    const { view, composerRevision } = useValues(sidepanelTicketsLogic)
    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    return (
        <>
            {view === 'list' && <QuillTicketsList />}
            {view === 'ticket' && <QuillTicket />}
            {/* Keyed on the composer revision, so a prefill or discard while the composer is open remounts the editor. */}
            {view === 'new' && <QuillNewTicket key={composerRevision} />}
            {view === 'restore' && !hasIdentityMode && <QuillRestoreTickets />}
        </>
    )
}
