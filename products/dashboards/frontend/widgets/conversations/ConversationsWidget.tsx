import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { LemonBadge, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

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
            className="border-b border-primary px-3 py-2.5 text-current hover:bg-fill-highlight-100 hover:text-current"
        >
            <div className="min-w-0 space-y-0.5">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-semibold" title={requesterName(ticket)}>
                        {requesterName(ticket)}
                    </span>
                    <span className="shrink-0 text-xs text-muted">#{ticket.ticket_number}</span>
                    <div className="ml-auto flex shrink-0 items-center gap-2">
                        <Tooltip title={channelLabel}>
                            <span className="flex size-3.5 items-center justify-center text-muted [&>svg]:size-3.5">
                                {channelIcon[ticket.channel_source]}
                            </span>
                        </Tooltip>
                        <TZLabel time={ticket.updated_at} className="w-20 text-right text-xs text-muted" />
                    </div>
                </div>
                <div className="flex min-w-0 items-center gap-2 text-sm text-muted">
                    <span
                        className={cn('truncate', ticket.unread_team_count > 0 && 'font-medium text-primary')}
                        title={ticketTitle(ticket)}
                    >
                        {stripMarkdown(ticketTitle(ticket))}
                    </span>
                    {ticket.unread_team_count > 0 ? (
                        <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                    ) : null}
                </div>
                <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
                    {assignee ? <span className="truncate">Assigned to {assignee}</span> : <span>Unassigned</span>}
                </div>
                <div className="flex items-center gap-1">
                    {ticket.priority ? (
                        <LemonTag type={priorityTagType(ticket.priority)}>{ticket.priority}</LemonTag>
                    ) : null}
                    <LemonTag type={statusTagType(ticket.status)}>{ticket.status.replace('_', ' ')}</LemonTag>
                    {ticket.sla_due_at ? <SlaDisplay slaDueAt={ticket.sla_due_at} className="ml-auto text-xs" /> : null}
                </div>
            </div>
        </Link>
    )
}

function ConversationsWidgetLoadingState(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex flex-col" aria-busy aria-label="Loading tickets">
                {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className="space-y-1 border-b border-primary px-3 py-2.5" aria-hidden>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-4 w-28" />
                            <LemonSkeleton className="h-3 w-8" />
                            <LemonSkeleton className="ml-auto h-3 w-16" />
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-4 w-3/5" />
                            <LemonSkeleton className="size-4 rounded-full" />
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-3 w-24" />
                        </div>
                        <div className="flex items-center gap-1">
                            <div className="ml-auto flex items-center gap-1">
                                <LemonSkeleton className="h-5 w-12 rounded" />
                                <LemonSkeleton className="h-5 w-10 rounded" />
                                <LemonSkeleton className="h-3 w-16" />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </WidgetCardContent>
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
        return <ConversationsWidgetLoadingState />
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
