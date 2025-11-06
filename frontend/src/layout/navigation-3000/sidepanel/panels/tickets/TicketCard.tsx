import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

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
    const { expandedTicketId, replyingToTicketId, replySuccessTicketId, replyToTicketLoading } =
        useValues(sidePanelTicketsLogic)
    const { setExpandedTicketId, setReplyingToTicketId, replyToTicket } = useActions(sidePanelTicketsLogic)

    const [replyText, setReplyText] = useState('')

    const isExpanded = expandedTicketId === ticket.id
    const isWaitingForYou = ticket.status === 'pending'
    const isShowingReplyForm = replyingToTicketId === ticket.id
    const showSuccessMessage = replySuccessTicketId === ticket.id

    const handleSendReply = (): void => {
        if (replyText.trim()) {
            replyToTicket({ ticketId: ticket.id, body: replyText })
            setReplyText('')
        }
    }

    return (
        <div className="border rounded p-3 mb-2 hover:border-primary transition-colors">
            <div onClick={() => setExpandedTicketId(isExpanded ? null : ticket.id)} className="cursor-pointer">
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

            {/* Reply Form (for "Waiting for you" tickets) */}
            {isExpanded && isWaitingForYou && (
                <div className="mt-3 pt-3 border-t">
                    {showSuccessMessage ? (
                        <div className="p-3 bg-success-highlight border border-success rounded text-sm">
                            Reply sent successfully! Refreshing ticket...
                        </div>
                    ) : isShowingReplyForm ? (
                        <div className="space-y-2">
                            <LemonTextAreaMarkdown
                                value={replyText}
                                onChange={setReplyText}
                                placeholder="Write your reply in markdown..."
                                minRows={3}
                            />
                            <div className="flex gap-2 justify-end">
                                <LemonButton
                                    type="secondary"
                                    onClick={() => {
                                        setReplyingToTicketId(null)
                                        setReplyText('')
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    onClick={handleSendReply}
                                    loading={replyToTicketLoading}
                                    disabledReason={!replyText.trim() ? 'Please enter a reply' : undefined}
                                >
                                    Send reply
                                </LemonButton>
                            </div>
                        </div>
                    ) : (
                        <LemonButton type="primary" onClick={() => setReplyingToTicketId(ticket.id)} fullWidth center>
                            Reply to ticket
                        </LemonButton>
                    )}
                </div>
            )}

            {/* Comments */}
            {isExpanded && ticket.comments && ticket.comments.length > 0 && (
                <div className="mt-3 pt-3 border-t space-y-3">
                    {ticket.comments.map((comment) => {
                        const isAgent = comment.is_agent
                        return (
                            <div key={comment.id} className={`flex ${isAgent ? 'justify-start' : 'justify-end'}`}>
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
