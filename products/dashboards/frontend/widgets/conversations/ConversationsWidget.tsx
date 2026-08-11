import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { LemonBadge, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { stripMarkdown } from 'lib/utils/markdown'
import { urls } from 'scenes/urls'

import { channelIcon } from 'products/conversations/frontend/components/Channels/ChannelsTag'
import { SlaDisplay } from 'products/conversations/frontend/components/SlaDisplay'
import { channelOptions, type TicketChannel } from 'products/conversations/frontend/types'

import {
    WIDGET_LIST_COUNT_TICKETS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WidgetLoadingState,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseConversationsWidgetConfig } from './conversationsWidgetConfigValidation'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

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

function requesterName(ticket: ConversationsWidgetTicket): string {
    return ticket.requester_name || ticket.requester_email
}

function statusTagType(status: string): 'success' | 'primary' | 'default' {
    if (status === 'resolved') {
        return 'success'
    }
    if (status === 'new') {
        return 'primary'
    }
    return 'default'
}

function priorityTagType(priority: string): 'danger' | 'caution' | 'warning' | 'default' {
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

function ConversationsWidgetRow({ ticket }: { ticket: ConversationsWidgetTicket }): JSX.Element {
    const assignee = assigneeName(ticket)
    const channelLabel = channelOptions.find((option) => option.value === ticket.channel_source)?.label
    return (
        <Link
            to={urls.supportTicketDetail(ticket.ticket_number)}
            target="_blank"
            subtle
            className="flex items-center gap-3 border-b border-primary px-3 py-2 text-current hover:bg-fill-highlight-100 hover:text-current"
        >
            <Tooltip title={channelLabel}>
                <span className="size-4 shrink-0 text-muted [&>svg]:size-4">{channelIcon[ticket.channel_source]}</span>
            </Tooltip>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="shrink-0 text-xs text-muted">#{ticket.ticket_number}</span>
                    <span className="truncate font-semibold" title={requesterName(ticket)}>
                        {requesterName(ticket)}
                    </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted">
                    <span
                        className={cn('truncate', ticket.unread_team_count > 0 && 'font-medium text-primary')}
                        title={ticketTitle(ticket)}
                    >
                        {stripMarkdown(ticketTitle(ticket))}
                    </span>
                    {ticket.unread_team_count > 0 ? (
                        <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                    ) : null}
                    {assignee ? <span className="truncate">{assignee}</span> : null}
                    <TZLabel time={ticket.updated_at} />
                </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
                <div className="flex items-center gap-1">
                    {ticket.priority ? (
                        <LemonTag type={priorityTagType(ticket.priority)}>{ticket.priority}</LemonTag>
                    ) : null}
                    <LemonTag type={statusTagType(ticket.status)}>{ticket.status.replace('_', ' ')}</LemonTag>
                </div>
                {ticket.sla_due_at ? <SlaDisplay slaDueAt={ticket.sla_due_at} className="text-xs" /> : null}
            </div>
        </Link>
    )
}

export function ConversationsWidget({
    result,
    loading,
    error,
    config,
    onRefresh,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ConversationsWidgetResult | null | undefined
    const tickets = payload?.results ?? []
    const parsedConfig = parseConversationsWidgetConfig(config)
    const hasActiveFilters =
        !!parsedConfig.savedViewId ||
        parsedConfig.status !== 'all' ||
        (parsedConfig.priorities?.length ?? 0) > 0 ||
        parsedConfig.channel !== 'all' ||
        (parsedConfig.assignees?.length ?? 0) > 0 ||
        !!parsedConfig.search

    if (loading) {
        return <WidgetLoadingState rowCount={5} className="p-3" />
    }
    if (error) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage variant="error" onRefresh={onRefresh} refreshing={loading}>
                    Couldn't load recent tickets. Try again.
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }
    if (tickets.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="conversations-widget-empty-state"
                    >
                        <HedgehogMagnifyingGlass className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">
                            {hasActiveFilters ? 'No tickets found' : 'No tickets yet'}
                        </p>
                        <p className="m-0 text-sm text-muted">
                            {hasActiveFilters
                                ? 'No tickets matched your filters.'
                                : 'New support tickets will appear here.'}
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
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
