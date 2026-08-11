import { IconMessage } from '@posthog/icons'
import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import {
    WIDGET_LIST_COUNT_TICKETS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'

export type ConversationsWidgetTicket = {
    id: string
    ticket_number: number
    channel_source: string
    status: string
    priority: string | null
    assignee: { user: { id: number; name: string } | null; role: { id: string; name: string } | null } | null
    updated_at: string
    last_message_text: string | null
    unread_team_count: number
    email_subject: string | null
}

export type ConversationsWidgetResult = {
    results?: ConversationsWidgetTicket[]
    hasMore?: boolean
    totalCount?: number
    totalCountCapped?: boolean
}

function ticketTitle(ticket: ConversationsWidgetTicket): string {
    return ticket.email_subject || ticket.last_message_text || `Ticket #${ticket.ticket_number}`
}

function assigneeName(ticket: ConversationsWidgetTicket): string | null {
    return ticket.assignee?.user?.name ?? ticket.assignee?.role?.name ?? null
}

function ConversationsWidgetRow({ ticket }: { ticket: ConversationsWidgetTicket }): JSX.Element {
    const assignee = assigneeName(ticket)
    return (
        <Link
            to={urls.supportTicketDetail(ticket.ticket_number)}
            target="_blank"
            subtle
            className={cn(
                'flex items-center gap-3 border-b px-3 py-2 text-current hover:bg-fill-highlight-100 hover:text-current',
                ticket.unread_team_count > 0 && 'bg-primary-alt-highlight'
            )}
        >
            <IconMessage className="size-4 shrink-0 text-muted" />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="shrink-0 text-xs text-muted">#{ticket.ticket_number}</span>
                    <span className="truncate font-semibold" title={ticketTitle(ticket)}>
                        {ticketTitle(ticket)}
                    </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted">
                    <span className="capitalize">{ticket.channel_source}</span>
                    {assignee ? <span className="truncate">{assignee}</span> : null}
                    <TZLabel time={ticket.updated_at} />
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
                {ticket.priority ? <LemonTag type="muted">{ticket.priority}</LemonTag> : null}
                <LemonTag type="muted">{ticket.status.replace('_', ' ')}</LemonTag>
            </div>
        </Link>
    )
}

export function ConversationsWidget({ result, loading, error }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ConversationsWidgetResult | null | undefined
    const tickets = payload?.results ?? []

    if (loading) {
        return (
            <WidgetCardContent>
                <div className="flex flex-col gap-3 p-3">
                    {Array.from({ length: 5 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-10 w-full" />
                    ))}
                </div>
            </WidgetCardContent>
        )
    }
    if (error) {
        return (
            <WidgetCardBodyMessage>
                Couldn't load recent tickets. Refresh the dashboard to try again.
            </WidgetCardBodyMessage>
        )
    }
    if (tickets.length === 0) {
        return <WidgetCardBodyMessage>No tickets match this status.</WidgetCardBodyMessage>
    }
    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {tickets.map((ticket) => (
                        <ConversationsWidgetRow key={ticket.id} ticket={ticket} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={tickets.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_TICKETS}
                    hasMore={payload?.hasMore}
                    dataAttr="conversations-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
