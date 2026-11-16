import { IconClock } from '@posthog/icons'
import {
    Badge,
    Button,
    type DataTableProps,
    Spinner,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { stripMarkdown } from 'lib/utils/markdown'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { AssigneeDisplay, AssigneeResolver } from '../../components/Assignee'
import { getChannelThreadUrl } from '../../components/Channels/ChannelsTag'
import { QuillChannelsTag } from '../../components/Channels/QuillChannelsTag'
import { QuillIdentityBadge } from '../../components/IdentityBadge/QuillIdentityBadge'
import { ticketStatusBadgeVariant } from '../../components/QuillSidePanel/ticketStatusBadgeVariant'
import { type SlaState, getSlaState } from '../../components/SlaDisplay/SlaDisplay'
import { TicketPreviewPopover } from '../../components/TicketPreview/TicketPreviewPopover'
import {
    type AITriageTagType,
    type Ticket,
    type TicketPriority,
    aiTriageProcessingLabel,
    sidePanelTicketFilterLabels,
    ticketListAiTriage,
} from '../../types'
import {
    type TicketColumnContext,
    type TicketColumnKey,
    aiTriageTooltip,
    isTicketColumnSortable,
    ticketColumnLabel,
    ticketPerson,
    visibleTicketColumnKeys,
} from './ticketColumns'

type TicketColumnDef = DataTableProps<Ticket, unknown>['columns'][number]

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>

const VISIBLE_TAGS = 2

const PRIORITY_BADGE: Record<TicketPriority, BadgeVariant> = {
    critical: 'destructive',
    high: 'warning',
    medium: 'warning',
    low: 'default',
}

const AI_TRIAGE_BADGE: Record<AITriageTagType, BadgeVariant> = {
    success: 'success',
    warning: 'warning',
    danger: 'destructive',
    default: 'default',
}

const SLA_TEXT: Record<SlaState, string> = {
    breached: 'text-destructive-foreground',
    'at-risk': 'text-warning-foreground',
    'on-track': 'text-success-foreground',
}

function NoValue(): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />}>
            —
        </Text>
    )
}

function Timestamp({ time }: { time: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
            <TZLabel time={time} />
        </Text>
    )
}

export interface QuillTicketColumnOptions extends TicketColumnContext {
    /** The URL the ticket number links to, with the list's query string. */
    ticketUrl: (ticket: Ticket) => string
}

function cellFor(key: TicketColumnKey, ticketUrl: (ticket: Ticket) => string): TicketColumnDef['cell'] {
    switch (key) {
        case 'ticket_number':
            return ({ row }) => (
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={ticketUrl(row.original)} />}
                    className="font-mono"
                >
                    {row.original.ticket_number}
                </Button>
            )
        case 'customer':
            return ({ row }) => (
                <div className="flex min-w-0 items-center gap-2">
                    <PersonDisplay person={ticketPerson(row.original)} withIcon />
                    {row.original.identity_verified === false && <QuillIdentityBadge verified={false} />}
                </div>
            )
        case 'last_message':
            return ({ row }) => {
                const ticket = row.original
                const unread = ticket.unread_team_count
                return (
                    <div className="flex min-w-0 items-center gap-2">
                        {ticket.last_message_text ? (
                            <TicketPreviewPopover ticketId={ticket.id}>
                                <Text
                                    size="xs"
                                    weight={unread > 0 ? 'medium' : 'normal'}
                                    variant={unread > 0 ? 'default' : 'muted'}
                                    render={<span />}
                                    className="block max-w-md truncate"
                                >
                                    {stripMarkdown(ticket.last_message_text)}
                                </Text>
                            </TicketPreviewPopover>
                        ) : (
                            <NoValue />
                        )}
                        {unread > 0 && (
                            <Badge variant="info" aria-label={`${unread} unread`}>
                                {unread}
                            </Badge>
                        )}
                    </div>
                )
            }
        case 'status':
            return ({ row }) => {
                const ticket = row.original
                return (
                    <span className="flex items-center gap-1">
                        <Badge variant={ticketStatusBadgeVariant(ticket.status)}>
                            {sidePanelTicketFilterLabels[ticket.status]}
                        </Badge>
                        {ticket.snoozed_until && (
                            <TZLabel time={ticket.snoozed_until} title="Snoozed until" showSeconds>
                                <span className="flex items-center text-muted-foreground">
                                    <IconClock />
                                </span>
                            </TZLabel>
                        )}
                    </span>
                )
            }
        case 'ai_triage':
            return ({ row }) => {
                const display = ticketListAiTriage(row.original.ai_triage)
                if (display.kind === 'empty') {
                    return <NoValue />
                }
                if (display.kind === 'processing') {
                    return (
                        <Text size="xs" render={<span />} className="flex items-center gap-1">
                            <Spinner />
                            {aiTriageProcessingLabel}
                        </Text>
                    )
                }
                const badge = <Badge variant={AI_TRIAGE_BADGE[display.tagType]}>{display.label}</Badge>
                const tooltip = aiTriageTooltip(row.original)
                if (!tooltip) {
                    return badge
                }
                return (
                    <Tooltip>
                        <TooltipTrigger render={badge} />
                        <TooltipContent>{tooltip}</TooltipContent>
                    </Tooltip>
                )
            }
        case 'priority':
            return ({ row }) =>
                row.original.priority ? (
                    <Badge variant={PRIORITY_BADGE[row.original.priority]} className="capitalize">
                        {row.original.priority}
                    </Badge>
                ) : (
                    <NoValue />
                )
        case 'sla_due_at':
            return ({ row }) => {
                const slaDueAt = row.original.sla_due_at
                if (!slaDueAt) {
                    return <NoValue />
                }
                return (
                    <TZLabel
                        time={slaDueAt}
                        className={cn('whitespace-nowrap text-xs font-medium', SLA_TEXT[getSlaState(slaDueAt)])}
                    />
                )
            }
        case 'assignee':
            return ({ row }) => (
                <AssigneeResolver assignee={row.original.assignee ?? null}>
                    {({ assignee }) => <AssigneeDisplay assignee={assignee} size="small" />}
                </AssigneeResolver>
            )
        case 'channel':
            return ({ row }) => (
                <QuillChannelsTag
                    channel={row.original.channel_source}
                    detail={row.original.channel_detail}
                    to={getChannelThreadUrl(row.original)}
                    emailTo={row.original.email_to}
                />
            )
        case 'tags':
            return ({ row }) => {
                const tags = row.original.tags ?? []
                if (tags.length === 0) {
                    return <NoValue />
                }
                return (
                    <div className="flex items-center gap-1">
                        {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                            <Badge key={tag} className="max-w-24 truncate">
                                {tag}
                            </Badge>
                        ))}
                        {tags.length > VISIBLE_TAGS && (
                            <Text
                                size="xs"
                                variant="muted"
                                render={<span />}
                                title={tags.slice(VISIBLE_TAGS).join(', ')}
                            >
                                {`+${tags.length - VISIBLE_TAGS}`}
                            </Text>
                        )}
                    </div>
                )
            }
        case 'created_at':
            return ({ row }) => <Timestamp time={row.original.created_at} />
        case 'updated_at':
            return ({ row }) => <Timestamp time={row.original.updated_at} />
    }
}

/** The quill twin of `buildTicketColumns`: same columns, order and sorting, with quill cells. */
export function buildQuillTicketColumns(
    visibleColumns: TicketColumnKey[],
    { ticketUrl, ...context }: QuillTicketColumnOptions
): TicketColumnDef[] {
    return visibleTicketColumnKeys(visibleColumns, context).map((key) => {
        const sortable = isTicketColumnSortable(key)
        return {
            id: key,
            // The table sorts on the server, so a sortable column only needs an accessor to show its header button.
            ...(sortable ? { accessorKey: key } : {}),
            header: ticketColumnLabel(key),
            enableSorting: sortable,
            // A new sort starts ascending, as in the table's other version.
            sortDescFirst: false,
            meta: {
                ...(key === 'last_message' ? { expand: true } : {}),
                ...(key === 'updated_at' ? { align: 'right' as const } : {}),
            },
            cell: cellFor(key, ticketUrl),
        }
    })
}
