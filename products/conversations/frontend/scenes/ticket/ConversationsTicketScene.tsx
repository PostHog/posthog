import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonCard, LemonDivider, LemonInput, LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { Message } from '../../components/Chat/Message'
import { type TicketSlaState, type TicketStatus, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { conversationsTicketSceneLogic } from './conversationsTicketSceneLogic'

export const scene: SceneExport<{ ticketId: string }> = {
    component: ConversationsTicketScene,
    logic: conversationsTicketSceneLogic,
    paramsToProps: ({ params: { ticketId } }) => ({ ticketId: ticketId || 'new' }),
}

function calculateSLA(lastMessageTimestamp: string): { timeRemaining: string; risk: TicketSlaState } {
    // Mock SLA calculation: assuming 1 hour (60 min) response time
    const SLA_MINUTES = 60
    const now = new Date()
    const lastMessage = new Date()

    // Parse time from format like "08:14" and set to today
    const [hours, minutes] = lastMessageTimestamp.split(':').map(Number)
    lastMessage.setHours(hours, minutes, 0, 0)

    const elapsedMinutes = Math.floor((now.getTime() - lastMessage.getTime()) / 1000 / 60)
    const remainingMinutes = SLA_MINUTES - elapsedMinutes

    let risk: TicketSlaState
    if (remainingMinutes < 0) {
        risk = 'breached'
    } else if (remainingMinutes < 15) {
        risk = 'at-risk'
    } else {
        risk = 'on-track'
    }

    return {
        timeRemaining:
            remainingMinutes > 0 ? `${remainingMinutes} min remaining` : `${Math.abs(remainingMinutes)} min overdue`,
        risk,
    }
}

export function ConversationsTicketScene({ ticketId }: { ticketId: string }): JSX.Element {
    const logic = conversationsTicketSceneLogic({ id: ticketId || 'new' })
    const {
        ticket,
        ticketLoading,
        status,
        priority,
        assignedTo,
        messages,
        messagesLoading,
        messageSending,
        hasMoreMessages,
        olderMessagesLoading,
    } = useValues(logic)
    const { setStatus, setPriority, setAssignedTo, sendMessage, updateTicket, loadOlderMessages } = useActions(logic)
    const { push } = useActions(router)

    const [showAiSuggestion, setShowAiSuggestion] = useState(true)
    const [messageContent, setMessageContent] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const messagesContainerRef = useRef<HTMLDivElement>(null)

    const scrollToBottom = (): void => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

    // Auto-calculate SLA based on last customer message
    const lastCustomerMessage = messages.length > 0 ? messages[messages.length - 1] : null
    const [slaData, setSlaData] = useState(
        calculateSLA(
            lastCustomerMessage?.created_at
                ? new Date(lastCustomerMessage.created_at).toLocaleTimeString('en-US', {
                      hour: '2-digit',
                      minute: '2-digit',
                      hour12: false,
                  })
                : '08:20'
        )
    )

    // Scroll to bottom when messages change
    useEffect(() => {
        if (messages.length > 0) {
            scrollToBottom()
        }
    }, [messages.length])

    useEffect(() => {
        const interval = setInterval(() => {
            if (lastCustomerMessage) {
                const timeString = new Date(lastCustomerMessage.created_at).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                })
                setSlaData(calculateSLA(timeString))
            }
        }, 30000) // Update every 30 seconds

        return () => clearInterval(interval)
    }, [lastCustomerMessage])

    const handleSendMessage = (): void => {
        if (messageContent.trim()) {
            sendMessage(messageContent)
            setMessageContent('')
        }
    }

    const handleScroll = (): void => {
        const container = messagesContainerRef.current
        if (!container || olderMessagesLoading || !hasMoreMessages) {
            return
        }

        // Check if scrolled to top (within 50px threshold)
        if (container.scrollTop < 50) {
            loadOlderMessages()
        }
    }

    if (ticketLoading) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <Spinner className="text-4xl" />
                </div>
            </SceneContent>
        )
    }

    const isNewTicket = ticketId === 'new'

    if (!ticket && !isNewTicket) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <h2 className="text-xl font-semibold mb-2">Ticket not found</h2>
                        <LemonButton type="primary" to={urls.conversationsTickets()}>
                            Back to tickets
                        </LemonButton>
                    </div>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={ticket?.id || ''}
                description=""
                resourceType={{ type: 'conversation' }}
                forceBackTo={{
                    name: 'Ticket list',
                    path: urls.conversationsTickets(),
                    key: 'conversationsTickets',
                }}
            />

            <div className="grid gap-4 lg:grid-cols-[1fr_380px] items-start">
                {/* Main conversation area */}
                <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden">
                    {/* Chat messages */}
                    <div
                        ref={messagesContainerRef}
                        onScroll={handleScroll}
                        className="flex-1 overflow-y-auto p-4 space-y-1.5 min-h-[400px] max-h-[600px]"
                    >
                        {olderMessagesLoading && (
                            <div className="flex items-center justify-center py-2">
                                <Spinner className="text-sm" />
                            </div>
                        )}
                        {messagesLoading && messages.length === 0 ? (
                            <div className="flex items-center justify-center h-full">
                                <Spinner />
                            </div>
                        ) : messages.length === 0 ? (
                            <div className="flex items-center justify-center h-full text-muted-alt text-sm">
                                No messages yet. Start the conversation!
                            </div>
                        ) : (
                            <>
                                {messages.map((message: any) => {
                                    const authorType = message.item_context?.author_type || 'customer'
                                    const isCustomer = authorType === 'customer'

                                    let displayName = 'Customer'
                                    if (message.created_by) {
                                        displayName =
                                            `${message.created_by.first_name} ${message.created_by.last_name}`.trim() ||
                                            message.created_by.email
                                    } else if (authorType === 'customer') {
                                        displayName =
                                            ticket?.anonymous_traits?.name ||
                                            ticket?.anonymous_traits?.email ||
                                            'Customer'
                                    }

                                    return (
                                        <Message
                                            key={message.id}
                                            message={message}
                                            isCustomer={isCustomer}
                                            displayName={displayName}
                                        />
                                    )
                                })}
                                <div ref={messagesEndRef} />
                            </>
                        )}
                    </div>

                    {/* AI suggested reply */}
                    {showAiSuggestion && ticket?.aiInsights && (
                        <div className="border-t border-b bg-accent-3000-light p-3">
                            <div className="flex items-start justify-between gap-2 mb-2">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-semibold">💡 AI suggested reply</span>
                                    <div className="flex flex-wrap gap-1">
                                        {ticket.aiInsights.referencedContent?.map((item: string) => (
                                            <LemonTag key={item} type="muted" size="small">
                                                {item}
                                            </LemonTag>
                                        ))}
                                    </div>
                                </div>
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    onClick={() => setShowAiSuggestion(false)}
                                    icon={<span className="text-xs">✕</span>}
                                />
                            </div>
                            <div className="text-xs p-2 bg-bg-light rounded border mb-2">
                                {ticket.aiInsights.suggestedReply}
                            </div>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => {
                                    setMessageContent(ticket.aiInsights.suggestedReply)
                                    setShowAiSuggestion(false)
                                }}
                            >
                                Use this reply
                            </LemonButton>
                        </div>
                    )}

                    {/* Reply input */}
                    <div className="border-t p-3">
                        <div className="flex gap-2">
                            <LemonInput
                                className="flex-1"
                                placeholder="Type your message..."
                                value={messageContent}
                                onChange={setMessageContent}
                                onPressEnter={handleSendMessage}
                                disabled={messageSending}
                            />
                            <LemonButton
                                type="primary"
                                onClick={handleSendMessage}
                                loading={messageSending}
                                disabled={!messageContent.trim()}
                            >
                                Send
                            </LemonButton>
                        </div>
                    </div>
                </LemonCard>

                {/* Sidebar with all metadata */}
                <div className="space-y-3">
                    {/* Customer */}
                    {ticket?.distinct_id && (
                        <LemonCard hoverEffect={false} className="p-3">
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-sm font-semibold">Customer</h3>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => push(urls.personByDistinctId(ticket.distinct_id))}
                                >
                                    View person
                                </LemonButton>
                            </div>
                            <PersonDisplay person={{ distinct_id: ticket.distinct_id }} withIcon />
                        </LemonCard>
                    )}
                    {/* Ticket info */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <h3 className="text-sm font-semibold mb-2">Ticket info</h3>
                        <div className="space-y-2 text-xs">
                            <div className="flex justify-between">
                                <PersonDisplay person={{ distinct_id: ticket.distinct_id }} withIcon />
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Created</span>
                                <span>
                                    <TZLabel time={ticket?.created_at} />
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Updated</span>
                                <span>
                                    <TZLabel time={ticket?.updated_at} />
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Channel</span>
                                <span className="capitalize">
                                    <ChannelsTag channel={ticket?.channel_source} />
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Status</span>
                                <LemonSelect
                                    size="small"
                                    value={status}
                                    options={statusOptionsWithoutAll}
                                    onChange={(value: TicketStatus | null) => value && setStatus(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Priority</span>
                                <LemonSelect
                                    size="small"
                                    value={priority}
                                    options={priorityOptions}
                                    onChange={(value: 'low' | 'medium' | 'high' | null) => value && setPriority(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Assignee</span>
                                <MemberSelect
                                    value={assignedTo === 'All users' ? null : assignedTo}
                                    onChange={(user) => setAssignedTo(user?.id || 'All users')}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">SLA</span>
                                <LemonTag
                                    type={
                                        slaData.risk === 'on-track'
                                            ? 'success'
                                            : slaData.risk === 'at-risk'
                                              ? 'warning'
                                              : 'danger'
                                    }
                                    size="small"
                                >
                                    {slaData.timeRemaining}
                                </LemonTag>
                            </div>
                        </div>
                        <div className="mt-3 pt-3 border-t">
                            <LemonButton type="primary" size="small" onClick={() => updateTicket()}>
                                Save changes
                            </LemonButton>
                        </div>
                    </LemonCard>

                    {/* Recent events */}
                    {ticket?.recentEvents && ticket.recentEvents.length > 0 && (
                        <LemonCard hoverEffect={false} className="p-3">
                            <h3 className="text-sm font-semibold mb-2">Recent events</h3>
                            <div className="space-y-2 text-xs">
                                {ticket.recentEvents.map((event: any, idx: number) => (
                                    <div key={event.id}>
                                        <div className="flex justify-between gap-2">
                                            <span className="flex-1">{event.description}</span>
                                            <span className="text-muted-alt whitespace-nowrap">{event.ts}</span>
                                        </div>
                                        {idx < ticket.recentEvents.length - 1 && (
                                            <LemonDivider dashed className="my-2" />
                                        )}
                                    </div>
                                ))}
                            </div>
                        </LemonCard>
                    )}

                    {/* Session recording */}
                    {ticket?.sessionRecording && (
                        <LemonCard hoverEffect={false} className="p-3">
                            <h3 className="text-sm font-semibold mb-2">Session recording</h3>
                            <p className="text-xs text-muted-alt mb-2">
                                {ticket.sessionRecording.id} · {ticket.sessionRecording.duration}
                            </p>
                            <div className="rounded border border-dashed border-light bg-bg-300 p-3 text-center text-xs text-muted-alt">
                                Recording preview
                            </div>
                            <LemonButton
                                className="mt-2"
                                type="secondary"
                                size="small"
                                to={ticket.sessionRecording.url}
                            >
                                Open in replay
                            </LemonButton>
                        </LemonCard>
                    )}

                    {/* Previous tickets */}
                    {ticket?.previousTickets && ticket.previousTickets.length > 0 && (
                        <LemonCard hoverEffect={false} className="p-3">
                            <h3 className="text-sm font-semibold mb-2">Previous tickets</h3>
                            <div className="space-y-2 text-xs">
                                {ticket.previousTickets.map((prevTicket: any) => (
                                    <div
                                        key={prevTicket.id}
                                        className="p-2 rounded border border-border-light hover:bg-bg-light cursor-pointer"
                                        onClick={() => push(urls.conversationsTicketDetail(prevTicket.id))}
                                    >
                                        <div className="font-medium">{prevTicket.subject}</div>
                                        <div className="text-muted-alt mt-0.5">
                                            {prevTicket.status} • {prevTicket.timeAgo}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <LemonButton className="mt-2" type="secondary" size="small">
                                View all tickets
                            </LemonButton>
                        </LemonCard>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
