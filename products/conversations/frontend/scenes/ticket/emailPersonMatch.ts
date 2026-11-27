import type { Ticket } from '../../types'

// An unverified relayed email can carry any sender address, so the person the ticket API matched
// by that address is not trusted. This mirrors _has_unverified_relayed_identity in backend/events.py.
export function isEmailPersonMatchTrusted(ticket: Pick<Ticket, 'anonymous_traits' | 'identity_verified'>): boolean {
    return !(ticket.anonymous_traits?.email_relayed === true && ticket.identity_verified !== true)
}
