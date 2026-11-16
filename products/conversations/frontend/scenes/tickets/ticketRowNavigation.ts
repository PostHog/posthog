import { combineUrl, router } from 'kea-router'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import type { Ticket } from '../../types'

/**
 * Carry the active filters / saved view (the list's query string) onto the ticket URL so the
 * ticket's back arrow can return to this exact view. Skip it when embedded (e.g. the person side
 * panel), where the host page's query string isn't the ticket filters.
 */
export function ticketRowUrl(ticket: Ticket, searchParams: Record<string, any>, embedded: boolean): string {
    return combineUrl(urls.supportTicketDetail(ticket.ticket_number), embedded ? {} : searchParams).url
}

/** Opens a ticket from the list: a cmd/ctrl-click or a middle-click opens it in a new tab. */
export function openTicketRow(ticketUrl: string, inNewTab: boolean): void {
    if (inNewTab) {
        newInternalTab(ticketUrl)
    } else {
        router.actions.push(ticketUrl)
    }
}
