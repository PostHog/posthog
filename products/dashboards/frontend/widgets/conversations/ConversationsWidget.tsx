import { BindLogic, useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconChevronDown } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { stripMarkdown } from 'lib/utils/markdown'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import {
    AssigneeDisplay,
    AssigneeResolver,
    AssigneeSelect,
    type TicketAssignee,
} from 'products/conversations/frontend/components/Assignee'
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
import { conversationsWidgetLogic } from './conversationsWidgetLogic'

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

function ticketAssignee(ticket: ConversationsWidgetTicket): TicketAssignee {
    if (ticket.assignee?.user) {
        return { type: 'user', id: ticket.assignee.user.id }
    }
    if (ticket.assignee?.role) {
        return { type: 'role', id: ticket.assignee.role.id }
    }
    return null
}

function ticketAssigneeName(ticket: ConversationsWidgetTicket): string | null {
    return ticket.assignee?.user?.name ?? ticket.assignee?.role?.name ?? null
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

function ConversationsWidgetRow({
    ticket,
    canMutateTickets,
}: {
    ticket: ConversationsWidgetTicket
    canMutateTickets: boolean
}): JSX.Element {
    const { ticketAssignmentLoadingId } = useValues(conversationsWidgetLogic)
    const { assignTicket } = useActions(conversationsWidgetLogic)
    const assignee = ticketAssignee(ticket)
    const assigneeName = ticketAssigneeName(ticket)
    const isAssignmentLoading = ticketAssignmentLoadingId === ticket.id
    const channelLabel = channelOptions.find((option) => option.value === ticket.channel_source)?.label
    return (
        <div className="border-b border-primary px-3 py-3 hover:bg-fill-highlight-100">
            <Link
                to={urls.supportTicketDetail(ticket.ticket_number)}
                target="_blank"
                subtle
                className="block text-current hover:text-current"
            >
                <div className="min-w-0 space-y-1.5">
                    <div className="flex min-w-0 items-center gap-2">
                        <PersonDisplay
                            person={{
                                distinct_id: ticket.requester_email,
                                properties: {
                                    name: ticket.requester_name ?? ticket.requester_email,
                                    email: ticket.requester_email,
                                },
                            }}
                            withIcon="sm"
                            noLink
                            noPopover
                            displayName={ticket.requester_name ?? ticket.requester_email}
                            className="min-w-0 truncate font-semibold"
                        />
                        <span className="shrink-0 text-xs text-muted">#{ticket.ticket_number}</span>
                        <div className="ml-auto flex shrink-0 items-center gap-1">
                            <Tooltip title={channelLabel}>
                                <span className="flex size-3.5 items-center justify-center text-muted [&>svg]:size-3.5">
                                    {channelIcon[ticket.channel_source]}
                                </span>
                            </Tooltip>
                            <span className="text-xs text-muted">Last updated</span>
                            <TZLabel time={ticket.updated_at} showPopover={false} className="text-xs text-muted" />
                        </div>
                    </div>
                    <div className="flex min-w-0 items-start gap-2 text-sm text-muted">
                        <div className="flex min-w-0 items-start gap-2">
                            <span
                                className={cn(
                                    'line-clamp-2',
                                    ticket.unread_team_count > 0 && 'font-medium text-primary'
                                )}
                                title={ticketTitle(ticket)}
                            >
                                {stripMarkdown(ticketTitle(ticket))}
                            </span>
                            {ticket.unread_team_count > 0 ? (
                                <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                            ) : null}
                        </div>
                        {ticket.sla_due_at ? (
                            <div className="ml-auto shrink-0 text-xs text-muted">
                                SLA due{' '}
                                <SlaDisplay slaDueAt={ticket.sla_due_at} showPopover={false} className="text-xs" />
                            </div>
                        ) : null}
                    </div>
                </div>
            </Link>
            <div className="mt-2 flex min-w-0 items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1">
                    {ticket.priority ? (
                        <LemonTag type={priorityTagType(ticket.priority)}>{ticket.priority}</LemonTag>
                    ) : null}
                    <LemonTag type={statusTagType(ticket.status)}>{ticket.status.replace('_', ' ')}</LemonTag>
                </div>
                <div onClick={(event) => event.stopPropagation()}>
                    {canMutateTickets ? (
                        <AssigneeSelect
                            assignee={assignee}
                            onChange={(nextAssignee) => assignTicket(ticket.id, nextAssignee)}
                            disabledReason={isAssignmentLoading ? 'Updating assignee...' : undefined}
                        >
                            {(resolvedAssignee, isOpen) => (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    active={isOpen}
                                    sideIcon={<IconChevronDown />}
                                    loading={isAssignmentLoading}
                                >
                                    <AssigneeDisplay
                                        assignee={resolvedAssignee}
                                        size="xsmall"
                                        placeholder={assigneeName ?? 'Unassigned'}
                                    />
                                </LemonButton>
                            )}
                        </AssigneeSelect>
                    ) : (
                        <AssigneeResolver assignee={assignee}>
                            {({ assignee: resolvedAssignee }) => (
                                <AssigneeDisplay
                                    assignee={resolvedAssignee}
                                    size="xsmall"
                                    placeholder={assigneeName ?? 'Unassigned'}
                                />
                            )}
                        </AssigneeResolver>
                    )}
                </div>
            </div>
        </div>
    )
}

function ConversationsWidgetLoadingState(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex flex-col" aria-busy aria-label="Loading tickets">
                {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className="space-y-1.5 border-b border-primary px-3 py-3" aria-hidden>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-4 w-28" />
                            <LemonSkeleton className="h-3 w-8" />
                            <LemonSkeleton className="ml-auto h-3 w-16" />
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-4 w-3/5" />
                            <LemonSkeleton className="size-4 rounded-full" />
                        </div>
                        <div className="flex items-center gap-1">
                            <LemonSkeleton className="h-3 w-24" />
                        </div>
                        <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1">
                                <LemonSkeleton className="h-5 w-12 rounded" />
                                <LemonSkeleton className="h-5 w-10 rounded" />
                            </div>
                            <LemonSkeleton className="h-5 w-16 rounded" />
                        </div>
                    </div>
                ))}
            </div>
        </WidgetCardContent>
    )
}

export function ConversationsWidget({
    tileId,
    result,
    loading,
    error,
    config,
    onRefresh,
    onRefreshData,
    canMutateConversationsTickets = false,
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
        <BindLogic logic={conversationsWidgetLogic} props={{ tileId, onRefreshData }}>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {tickets.map((ticket) => (
                        <ConversationsWidgetRow
                            key={ticket.id}
                            ticket={ticket}
                            canMutateTickets={canMutateConversationsTickets}
                        />
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
        </BindLogic>
    )
}
