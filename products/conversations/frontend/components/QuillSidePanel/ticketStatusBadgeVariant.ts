import type { TicketStatus } from '../../types'

/** The quill Badge variant for a ticket status: resolved reads as done, a new ticket as fresh, the rest stay neutral. */
export function ticketStatusBadgeVariant(status: TicketStatus | undefined): 'success' | 'info' | 'default' {
    return status === 'resolved' ? 'success' : status === 'new' ? 'info' : 'default'
}
