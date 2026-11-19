import { dayjs } from 'lib/dayjs'

import type { PatchedTicketUpdateRequestApi } from 'products/conversations/frontend/generated/api.schemas'

import { isSameAssigneeEntry, type TicketAssignee } from '../../components/Assignee/types'
import type { Ticket, TicketPriority, TicketStatus } from '../../types'

export interface TicketFieldEdits {
    status: TicketStatus | null
    priority: TicketPriority | null
    assignee: TicketAssignee
    tags: string[]
    snoozedUntil: string | null
}

// Only fields that differ from the saved ticket go in the PATCH: sending an unchanged field would
// overwrite whatever a teammate saved to it since this page last loaded the ticket.
export function changedTicketFields(edits: TicketFieldEdits, ticket: Ticket): PatchedTicketUpdateRequestApi {
    const changes: PatchedTicketUpdateRequestApi = {}
    if (edits.status && edits.status !== ticket.status) {
        changes.status = edits.status
    }
    if (edits.priority && edits.priority !== ticket.priority) {
        changes.priority = edits.priority
    }
    if (!isSameAssigneeEntry(edits.assignee ?? 'unassigned', ticket.assignee ?? 'unassigned')) {
        changes.assignee = edits.assignee
    }
    if (JSON.stringify([...edits.tags].sort()) !== JSON.stringify([...(ticket.tags || [])].sort())) {
        changes.tags = edits.tags
    }
    const snoozedUnix = edits.snoozedUntil ? dayjs(edits.snoozedUntil).unix() : null
    const savedSnoozedUnix = ticket.snoozed_until ? dayjs(ticket.snoozed_until).unix() : null
    if (snoozedUnix !== savedSnoozedUnix) {
        changes.snoozed_until = edits.snoozedUntil
    }
    return changes
}
