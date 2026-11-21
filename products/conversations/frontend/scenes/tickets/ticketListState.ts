import type { Ticket, TicketStatus } from '../../types'

export interface TicketBulkActionState {
    /** The status every selected ticket shares, 'mixed' when they differ, null with no selection. */
    currentStatus: TicketStatus | 'mixed' | null
    /** Why a bulk action can't run on the selection. Undefined when it can. */
    noEditableSelectionReason: string | undefined
    /** Warns that the action skips part of the selection. */
    restrictedSelectionTooltip: string | undefined
}

export function ticketBulkActionState(
    selectedTicketIds: string[],
    selectedTickets: Ticket[],
    editableTicketIds: string[]
): TicketBulkActionState {
    const hasSelection = selectedTicketIds.length > 0
    const hasRestrictedSelection = editableTicketIds.length < selectedTicketIds.length
    const currentStatus = selectedTickets
        .map((ticket) => ticket.status)
        .reduce<TicketStatus | 'mixed' | null>((acc, status) => {
            if (acc === null) {
                return status
            }
            return acc === status ? acc : 'mixed'
        }, null)

    return {
        currentStatus,
        noEditableSelectionReason: !hasSelection
            ? 'Select tickets first'
            : editableTicketIds.length === 0
              ? "You don't have edit access to any of the selected tickets"
              : undefined,
        restrictedSelectionTooltip:
            hasRestrictedSelection && editableTicketIds.length > 0
                ? `${selectedTicketIds.length - editableTicketIds.length} selected ticket(s) will be skipped because you don't have edit access to them`
                : undefined,
    }
}

/** What an empty ticket list says: a search narrowed by filters offers to search again without them. */
export type TicketListEmptyKind = 'search-with-filters' | 'no-tickets'

/** 'failed' lasts until the next successful load, so a failed first load can show an error instead of an empty list. */
export type TicketsLoadState = 'unloaded' | 'loaded' | 'failed'
