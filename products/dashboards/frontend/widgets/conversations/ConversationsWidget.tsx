import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconChevronDown } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { stripMarkdown } from 'lib/utils/markdown'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AssigneeDisplay, AssigneeResolver, AssigneeSelect } from 'products/conversations/frontend/components/Assignee'
import { channelIcon } from 'products/conversations/frontend/components/Channels/ChannelsTag'
import { channelOptions } from 'products/conversations/frontend/types'

import {
    WIDGET_LIST_COUNT_TICKETS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetTopHeadingProps } from '../../components/WidgetCard/WidgetCardHeader'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseConversationsWidgetConfig } from './conversationsWidgetConfigValidation'
import { conversationsWidgetLogic } from './conversationsWidgetLogic'
import { conversationsWidgetSavedViewsLogic } from './conversationsWidgetSavedViewsLogic'
import {
    priorityTagType,
    statusTagType,
    ticketAssignee,
    ticketAssigneeName,
    ticketTitle,
    TicketSlaIcon,
    type ConversationsWidgetTicket,
} from './conversationsWidgetUtils'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export type { ConversationsWidgetTicket } from './conversationsWidgetUtils'

export type ConversationsWidgetResult = {
    results?: ConversationsWidgetTicket[]
    hasMore?: boolean
    totalCount?: number
    totalCountCapped?: boolean
}

export function ConversationsWidgetTopHeading({
    config,
    widgetTypeLabel,
    showWidgetType,
    dateText,
}: DashboardWidgetTopHeadingProps): JSX.Element {
    const savedViewId = parseConversationsWidgetConfig(config).savedViewId
    const { currentProjectId } = useValues(teamLogic)
    const savedViewsLogic = conversationsWidgetSavedViewsLogic({ projectId: currentProjectId })
    const { savedViewLabelById, savedViewsLoaded, savedViewsLoading } = useValues(savedViewsLogic)
    const { loadSavedViews } = useActions(savedViewsLogic)

    useEffect(() => {
        if (savedViewId && !savedViewsLoaded && !savedViewsLoading) {
            loadSavedViews()
        }
    }, [loadSavedViews, savedViewId, savedViewsLoaded, savedViewsLoading])

    return (
        <CardTopHeadingRow
            typeLabel={widgetTypeLabel}
            showTypeLabel={showWidgetType}
            dateText={savedViewId ? (savedViewLabelById[savedViewId] ?? 'Saved view') : dateText}
        />
    )
}

function ConversationsWidgetRow({
    tileId,
    ticket,
    canMutateTickets,
}: {
    tileId: number
    ticket: ConversationsWidgetTicket
    canMutateTickets: boolean
}): JSX.Element {
    const { ticketAssignmentLoadingId } = useValues(conversationsWidgetLogic)
    const { assignTicket } = useActions(conversationsWidgetLogic)
    const assignee = ticketAssignee(ticket)
    const assigneeName = ticketAssigneeName(ticket)
    const isAssignmentLoading = ticketAssignmentLoadingId === ticket.id
    const assignmentDisabledReason = ticketAssignmentLoadingId ? 'Updating assignee...' : undefined
    const channelLabel = channelOptions.find((option) => option.value === ticket.channel_source)?.label
    const captureTicketOpened = (): void => {
        posthog.capture('dashboard widget open support ticket clicked', {
            widget_type: 'conversations_recent_tickets',
            tile_id: tileId,
            ticket_id: ticket.id,
        })
    }
    return (
        <div className="border-b border-primary px-3 py-3 hover:bg-fill-highlight-100">
            <div className="flex min-w-0 items-center gap-2">
                <Link
                    to={urls.supportTicketDetail(ticket.ticket_number)}
                    target="_blank"
                    subtle
                    className="min-w-0 flex-1 text-current hover:text-current"
                    onClick={captureTicketOpened}
                >
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
                        <Tooltip title={channelLabel}>
                            <span className="flex size-3.5 shrink-0 items-center justify-center text-muted [&>svg]:size-3.5">
                                {channelIcon[ticket.channel_source]}
                            </span>
                        </Tooltip>
                        <TicketSlaIcon slaDueAt={ticket.sla_due_at} />
                    </div>
                </Link>
                <div>
                    {canMutateTickets ? (
                        <AssigneeSelect
                            assignee={assignee}
                            onChange={(nextAssignee) => assignTicket(ticket.id, nextAssignee)}
                            disabledReason={assignmentDisabledReason}
                            loadOnOpen
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
            <Link
                to={urls.supportTicketDetail(ticket.ticket_number)}
                target="_blank"
                subtle
                className="mt-1.5 block min-w-0 text-current hover:text-current"
                onClick={captureTicketOpened}
            >
                <div className="flex min-w-0 items-start gap-2 text-sm text-muted">
                    <span
                        className={cn('line-clamp-2', ticket.unread_team_count > 0 && 'font-medium text-primary')}
                        title={ticketTitle(ticket)}
                    >
                        {stripMarkdown(ticketTitle(ticket))}
                    </span>
                    {ticket.unread_team_count > 0 ? (
                        <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                    ) : null}
                </div>
            </Link>
            <div className="mt-1.5 flex min-w-0 items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1">
                    {ticket.priority ? (
                        <LemonTag type={priorityTagType(ticket.priority)}>{ticket.priority}</LemonTag>
                    ) : null}
                    <LemonTag type={statusTagType(ticket.status)}>{ticket.status.replace('_', ' ')}</LemonTag>
                </div>
                <TZLabel time={ticket.updated_at} showPopover={false} className="shrink-0 text-xs text-muted" />
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
                        <div className="flex items-start gap-2">
                            <LemonSkeleton className="h-8 w-3/4" />
                            <LemonSkeleton className="mt-0.5 size-4 rounded-full" />
                        </div>
                        <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1">
                                <LemonSkeleton className="h-5 w-12 rounded" />
                                <LemonSkeleton className="h-5 w-10 rounded" />
                            </div>
                            <LemonSkeleton className="h-3 w-16" />
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
                            tileId={tileId}
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
