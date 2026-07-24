import clsx from 'clsx'

import { IconClock } from '@posthog/icons'
import { LemonBadge, LemonTableColumns, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { stripMarkdown } from 'lib/utils/markdown'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { AssigneeDisplay, AssigneeResolver } from '../../components/Assignee'
import { ChannelsTag, getChannelThreadUrl } from '../../components/Channels/ChannelsTag'
import { IdentityBadge } from '../../components/IdentityBadge/IdentityBadge'
import { SlaDisplay } from '../../components/SlaDisplay'
import { TicketPreviewPopover } from '../../components/TicketPreview/TicketPreviewPopover'
import {
    type Ticket,
    aiTriageProcessingLabel,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageTicketTypeLabel,
} from '../../types'
import { planLabel } from './planTags'

export type TicketColumnKey =
    | 'ticket_number'
    | 'customer'
    | 'last_message'
    | 'status'
    | 'ai_triage'
    | 'priority'
    | 'plan'
    | 'sla_due_at'
    | 'assignee'
    | 'channel'
    | 'tags'
    | 'created_at'
    | 'updated_at'

interface TicketColumnDefinition {
    label: string
    /** Only offered (and only rendered) when AI suggestions are enabled for the team. */
    aiOnly?: boolean
    /** Only offered (and only rendered) to PostHog staff — internal triage
     *  concepts that aren't (yet) meaningful or configurable for customers. */
    staffOnly?: boolean
    /** Hidden in embedded tables, which are already scoped to one person. */
    hiddenWhenEmbedded?: boolean
    /** Identifies the row, so it can't be hidden. */
    mandatory?: boolean
    column: LemonTableColumns<Ticket>[number]
}

const TICKET_COLUMNS: Record<TicketColumnKey, TicketColumnDefinition> = {
    ticket_number: {
        label: 'Ticket',
        mandatory: true,
        column: {
            title: 'Ticket',
            key: 'ticket_number',
            width: 80,
            sorter: true,
            render: (_, ticket) => <span className="text-xs font-mono text-muted-alt">{ticket.ticket_number}</span>,
        },
    },
    customer: {
        label: 'Person',
        hiddenWhenEmbedded: true,
        column: {
            title: 'Person',
            key: 'customer',
            render: (_, ticket) => (
                <div className="flex items-center gap-2">
                    <PersonDisplay
                        person={
                            ticket.person
                                ? {
                                      id: ticket.person.id,
                                      distinct_id: ticket.distinct_id,
                                      distinct_ids: ticket.person.distinct_ids,
                                      // Merge anonymous_traits as fallback for missing person properties
                                      properties: {
                                          ...ticket.anonymous_traits,
                                          ...ticket.person.properties,
                                      },
                                  }
                                : {
                                      distinct_id: ticket.distinct_id,
                                      properties: ticket.anonymous_traits || {},
                                  }
                        }
                        withIcon
                    />
                    {ticket.identity_verified === false && <IdentityBadge verified={false} iconOnly />}
                </div>
            ),
        },
    },
    last_message: {
        label: 'Last message',
        column: {
            title: 'Last message',
            key: 'last_message',
            render: (_, ticket) => (
                <div className="flex items-center gap-2">
                    {ticket.last_message_text ? (
                        <TicketPreviewPopover ticketId={ticket.id}>
                            <span
                                className={clsx('inline-block text-xs truncate max-w-md', {
                                    'text-muted-alt': ticket.unread_team_count === 0,
                                    'font-medium': ticket.unread_team_count > 0,
                                })}
                            >
                                {stripMarkdown(ticket.last_message_text)}
                            </span>
                        </TicketPreviewPopover>
                    ) : (
                        <span className="text-muted-alt text-xs">—</span>
                    )}
                    {ticket.unread_team_count > 0 && (
                        <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                    )}
                </div>
            ),
        },
    },
    status: {
        label: 'Status',
        column: {
            title: 'Status',
            key: 'status',
            render: (_, ticket) => (
                <span className="flex items-center gap-1">
                    <LemonTag
                        type={
                            ticket.status === 'resolved' ? 'success' : ticket.status === 'new' ? 'primary' : 'default'
                        }
                    >
                        {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                    </LemonTag>
                    {ticket.snoozed_until && (
                        <span title={`Snoozed until ${new Date(ticket.snoozed_until).toLocaleString()}`}>
                            <IconClock className="text-muted-alt text-base" />
                        </span>
                    )}
                </span>
            ),
        },
    },
    ai_triage: {
        label: 'AI status',
        aiOnly: true,
        column: {
            title: 'AI status',
            key: 'ai_triage',
            render: (_, ticket) => {
                const triage = ticket.ai_triage
                if (!triage || !triage.status) {
                    return <span className="text-muted-alt text-xs">—</span>
                }
                if (triage.status === 'in_progress') {
                    return (
                        <span className="flex items-center gap-1 text-xs">
                            <Spinner className="text-sm" />
                            {aiTriageProcessingLabel}
                        </span>
                    )
                }
                if (triage.result) {
                    const tooltipContent = [
                        triage.ticket_type &&
                            `Type: ${aiTriageTicketTypeLabel[triage.ticket_type] ?? triage.ticket_type}`,
                        triage.confidence != null && `Confidence: ${(triage.confidence * 100).toFixed(0)}%`,
                        triage.attempts != null && `Attempts: ${triage.attempts}`,
                    ]
                        .filter(Boolean)
                        .join(' · ')
                    return (
                        <Tooltip title={tooltipContent || undefined}>
                            <LemonTag type={aiTriageResultTagType(triage.result)}>
                                {aiTriageResultLabel[triage.result]}
                            </LemonTag>
                        </Tooltip>
                    )
                }
                return <span className="text-muted-alt text-xs">—</span>
            },
        },
    },
    priority: {
        label: 'Priority',
        column: {
            title: 'Priority',
            key: 'priority',
            render: (_, ticket) =>
                ticket.priority ? (
                    <LemonTag
                        type={
                            ticket.priority === 'critical'
                                ? 'danger'
                                : ticket.priority === 'high'
                                  ? 'caution'
                                  : ticket.priority === 'medium'
                                    ? 'warning'
                                    : 'default'
                        }
                    >
                        {ticket.priority}
                    </LemonTag>
                ) : (
                    <span className="text-muted-alt text-xs">—</span>
                ),
        },
    },
    plan: {
        label: 'Plan',
        staffOnly: true,
        column: {
            title: 'Plan',
            key: 'plan',
            sorter: true,
            render: (_, ticket) => {
                const label = planLabel(ticket.tags)
                return (
                    <span className="text-xs whitespace-nowrap" title={label}>
                        {label}
                    </span>
                )
            },
        },
    },
    sla_due_at: {
        label: 'SLA',
        column: {
            title: 'SLA',
            key: 'sla_due_at',
            sorter: true,
            render: (_, ticket) =>
                ticket.sla_due_at ? (
                    <SlaDisplay slaDueAt={ticket.sla_due_at} className="text-xs" />
                ) : (
                    <span className="text-muted-alt text-xs">—</span>
                ),
        },
    },
    assignee: {
        label: 'Assignee',
        column: {
            title: 'Assignee',
            key: 'assignee',
            render: (_, ticket) => (
                <AssigneeResolver assignee={ticket.assignee ?? null}>
                    {({ assignee }) => <AssigneeDisplay assignee={assignee} size="small" />}
                </AssigneeResolver>
            ),
        },
    },
    channel: {
        label: 'Channel',
        column: {
            title: 'Channel',
            key: 'channel',
            render: (_, ticket) => (
                <ChannelsTag
                    channel={ticket.channel_source}
                    detail={ticket.channel_detail}
                    to={getChannelThreadUrl(ticket)}
                />
            ),
        },
    },
    tags: {
        label: 'Tags',
        column: {
            title: 'Tags',
            key: 'tags',
            render: (_, ticket) =>
                ticket.tags && ticket.tags.length > 0 ? (
                    <ObjectTags tags={ticket.tags} staticOnly />
                ) : (
                    <span className="text-muted-alt text-xs">—</span>
                ),
        },
    },
    created_at: {
        label: 'Created',
        column: {
            title: 'Created',
            key: 'created_at',
            sorter: true,
            render: (_, ticket) => {
                return (
                    <span className="text-xs text-muted-alt">
                        {ticket.created_at && typeof ticket.created_at === 'string' && (
                            <TZLabel time={ticket.created_at} />
                        )}
                    </span>
                )
            },
        },
    },
    updated_at: {
        label: 'Updated',
        column: {
            title: 'Updated',
            key: 'updated_at',
            sorter: true,
            align: 'right',
            render: (_, ticket) => {
                return (
                    <span className="text-xs text-muted-alt">
                        {ticket.updated_at && typeof ticket.updated_at === 'string' && (
                            <TZLabel time={ticket.updated_at} />
                        )}
                    </span>
                )
            },
        },
    },
}

/** Canonical left-to-right order. Visible columns always render in this order. */
export const TICKET_COLUMN_ORDER: TicketColumnKey[] = [
    'ticket_number',
    'customer',
    'last_message',
    'status',
    'ai_triage',
    'priority',
    'plan',
    'sla_due_at',
    'assignee',
    'channel',
    'tags',
    'created_at',
    'updated_at',
]

export const DEFAULT_TICKET_COLUMNS: TicketColumnKey[] = [...TICKET_COLUMN_ORDER]

export function ticketColumnLabel(key: TicketColumnKey): string {
    return TICKET_COLUMNS[key].label
}

export function isTicketColumnMandatory(key: TicketColumnKey): boolean {
    return !!TICKET_COLUMNS[key].mandatory
}

interface TicketColumnContext {
    aiEnabled: boolean
    embedded: boolean
    /** Whether the viewer is PostHog staff (user.is_staff). */
    staff: boolean
}

/** The columns a user can actually choose between, given the current context. */
export function offerableTicketColumns({ aiEnabled, embedded, staff }: TicketColumnContext): TicketColumnKey[] {
    return TICKET_COLUMN_ORDER.filter((key) => {
        const definition = TICKET_COLUMNS[key]
        if (definition.aiOnly && !aiEnabled) {
            return false
        }
        if (definition.staffOnly && !staff) {
            return false
        }
        if (definition.hiddenWhenEmbedded && embedded) {
            return false
        }
        return true
    })
}

export function buildTicketColumns(
    visibleColumns: TicketColumnKey[],
    context: TicketColumnContext
): LemonTableColumns<Ticket> {
    const visible = new Set(visibleColumns)
    return offerableTicketColumns(context)
        .filter((key) => visible.has(key) || isTicketColumnMandatory(key))
        .map((key) => TICKET_COLUMNS[key].column)
}
