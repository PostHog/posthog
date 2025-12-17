import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonCard, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { UserBasicType } from '~/types'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { Message } from '../../components/Chat/Message'
import { type TicketPriority, type TicketStatus, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { conversationsTicketSceneLogic } from './conversationsTicketSceneLogic'

export const scene: SceneExport<{ ticketId: string }> = {
    component: ConversationsTicketScene,
    logic: conversationsTicketSceneLogic,
    paramsToProps: ({ params: { ticketId } }) => ({ ticketId: ticketId || 'new' }),
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

    const [messageContent, setMessageContent] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const messagesContainerRef = useRef<HTMLDivElement>(null)

    const scrollToBottom = (): void => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

    // Scroll to bottom when messages change
    useEffect(() => {
        if (messages.length > 0) {
            scrollToBottom()
        }
    }, [messages.length])

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
                <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden p-3">
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
                <LemonCard hoverEffect={false} className="p-3">
                    {/* Customer */}
                    {ticket?.distinct_id && (
                        <>
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
                            <div className="my-3 border-t" />
                        </>
                    )}

                    {/* Ticket info */}
                    <h3 className="text-sm font-semibold mb-2">Ticket info</h3>
                    <div className="space-y-2 text-xs">
                        {ticket?.created_at && (
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Created</span>
                                <span>
                                    <TZLabel time={ticket.created_at} />
                                </span>
                            </div>
                        )}
                        {ticket?.updated_at && (
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Updated</span>
                                <span>
                                    <TZLabel time={ticket.updated_at} />
                                </span>
                            </div>
                        )}
                        {ticket?.channel_source && (
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Channel</span>
                                <span className="capitalize">
                                    <ChannelsTag channel={ticket.channel_source} />
                                </span>
                            </div>
                        )}
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
                                onChange={(value: TicketPriority | null) => value && setPriority(value)}
                                dropdownMatchSelectWidth={false}
                            />
                        </div>
                        <div className="flex justify-between items-center">
                            <span className="text-muted-alt">Assignee</span>
                            <MemberSelect
                                value={
                                    !assignedTo || assignedTo === 'All users' || typeof assignedTo === 'string'
                                        ? null
                                        : assignedTo
                                }
                                onChange={(user: UserBasicType | null) =>
                                    setAssignedTo(user?.id?.toString() || ('All users' as string))
                                }
                            />
                        </div>
                    </div>
                    <div className="mt-3 pt-3 border-t flex justify-end">
                        <LemonButton type="primary" size="small" onClick={() => updateTicket()}>
                            Save changes
                        </LemonButton>
                    </div>
                </LemonCard>
            </div>
        </SceneContent>
    )
}
