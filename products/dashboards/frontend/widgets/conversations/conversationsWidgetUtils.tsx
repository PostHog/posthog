import { IconCheckCircle, IconClock, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { TicketAssignee } from 'products/conversations/frontend/components/Assignee'
import { getSlaState } from 'products/conversations/frontend/components/SlaDisplay'
import type { TicketChannel } from 'products/conversations/frontend/types'

export type ConversationsWidgetTicket = {
    id: string
    ticket_number: number
    channel_source: TicketChannel
    status: string
    priority: string | null
    assignee: { user: { id: number; name: string } | null; role: { id: string; name: string } | null } | null
    updated_at: string
    last_message_text: string | null
    unread_team_count: number
    email_subject: string | null
    requester_name: string | null
    requester_email: string
    sla_due_at: string | null
}

export function ticketTitle(ticket: ConversationsWidgetTicket): string {
    return ticket.email_subject || ticket.last_message_text || `Ticket #${ticket.ticket_number}`
}

export function ticketAssignee(ticket: ConversationsWidgetTicket): TicketAssignee {
    if (ticket.assignee?.user) {
        return { type: 'user', id: ticket.assignee.user.id }
    }
    if (ticket.assignee?.role) {
        return { type: 'role', id: ticket.assignee.role.id }
    }
    return null
}

export function ticketAssigneeName(ticket: ConversationsWidgetTicket): string | null {
    return ticket.assignee?.user?.name ?? ticket.assignee?.role?.name ?? null
}

export function statusTagType(status: string): 'success' | 'primary' | 'default' {
    if (status === 'resolved') {
        return 'success'
    }
    if (status === 'new') {
        return 'primary'
    }
    return 'default'
}

export function priorityTagType(priority: string): 'danger' | 'caution' | 'warning' | 'default' {
    if (priority === 'critical') {
        return 'danger'
    }
    if (priority === 'high') {
        return 'caution'
    }
    if (priority === 'medium') {
        return 'warning'
    }
    return 'default'
}

export function TicketSlaIcon({ slaDueAt }: { slaDueAt: string | null }): JSX.Element | null {
    if (!slaDueAt) {
        return null
    }

    const slaState = getSlaState(slaDueAt)
    let icon = <IconCheckCircle className="text-success" />
    let tooltip = 'SLA on track'

    if (slaState === 'breached') {
        icon = <IconWarning className="text-danger" />
        tooltip = 'SLA breached'
    } else if (slaState === 'at-risk') {
        icon = <IconClock className="text-warning" />
        tooltip = 'SLA due soon'
    }
    tooltip = `${tooltip}. Due ${dayjs(slaDueAt).fromNow()}`

    return (
        <Tooltip title={tooltip}>
            <span
                role="img"
                aria-label={tooltip}
                tabIndex={0}
                className="flex size-3.5 shrink-0 items-center justify-center [&>svg]:size-3.5"
            >
                {icon}
            </span>
        </Tooltip>
    )
}
