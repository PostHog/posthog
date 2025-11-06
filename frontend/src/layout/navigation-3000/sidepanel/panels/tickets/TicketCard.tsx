import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ZendeskTicket } from '~/types'

import { sidePanelTicketsLogic } from '../sidePanelTicketsLogic'

interface TicketCardProps {
    ticket: ZendeskTicket
}

const STATUS_COLORS: Record<string, 'primary' | 'warning' | 'success' | 'danger' | 'default'> = {
    new: 'primary',
    open: 'primary',
    pending: 'warning',
    hold: 'warning',
    solved: 'success',
    closed: 'default',
}

const STATUS_LABELS: Record<string, string> = {
    pending: 'Waiting for you',
}

export function TicketCard({ ticket }: TicketCardProps): JSX.Element {
    const { expandedTicketId } = useValues(sidePanelTicketsLogic)
    const { setExpandedTicketId } = useActions(sidePanelTicketsLogic)

    const isExpanded = expandedTicketId === ticket.id

    return (
        <div className="border rounded p-3 mb-2 hover:border-primary transition-colors cursor-pointer">
            <div onClick={() => setExpandedTicketId(isExpanded ? null : ticket.id)}>
                {/* Header */}
                <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <LemonButton
                            size="small"
                            icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                            noPadding
                        />
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                            <span className="text-xs text-muted shrink-0">#{ticket.id}</span>
                            <h4 className="font-semibold truncate">{ticket.subject}</h4>
                            <span className="text-muted shrink-0">·</span>
                            <TZLabel time={ticket.updated_at} className="text-xs text-muted shrink-0" />
                        </div>
                    </div>
                    <LemonTag type={STATUS_COLORS[ticket.status] || 'default'} size="small">
                        {STATUS_LABELS[ticket.status] || ticket.status}
                    </LemonTag>
                </div>

                {/* Description Preview (when collapsed) */}
                {!isExpanded && ticket.description && (
                    <p className="text-sm text-muted line-clamp-2 ml-8">{ticket.description}</p>
                )}
            </div>

            {/* Comments */}
            {isExpanded && ticket.comments && ticket.comments.length > 0 && (
                <div className="mt-3 pt-3 border-t space-y-3">
                    {ticket.comments.map((comment) => {
                        const isAgent = comment.is_agent
                        return (
                            <div
                                key={comment.id}
                                className={`flex ${isAgent ? 'justify-start' : 'justify-end'}`}
                            >
                                <div
                                    className={`rounded p-3 border max-w-[85%] ${
                                        isAgent
                                            ? 'bg-bg-light border-border ml-2'
                                            : 'bg-primary-alt-highlight border-primary mr-2'
                                    }`}
                                >
                                    <div className="flex items-center justify-between gap-2 mb-2">
                                        <div className="flex items-center gap-2">
                                            <span className={`font-medium text-sm ${!isAgent ? 'text-primary' : ''}`}>
                                                {comment.author_name}
                                            </span>
                                            {isAgent ? (
                                                <LemonTag size="small" type="completion">
                                                    Agent
                                                </LemonTag>
                                            ) : (
                                                <LemonTag size="small" type="primary">
                                                    You
                                                </LemonTag>
                                            )}
                                        </div>
                                        <TZLabel time={comment.created_at} className="text-xs text-muted shrink-0" />
                                    </div>
                                    <p className="text-sm whitespace-pre-wrap">{comment.body}</p>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

