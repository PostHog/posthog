import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconChevronRight } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonInput, LemonTag, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ConversationMessage, ConversationTicket, sidePanelConversationsLogic } from './sidePanelConversationsLogic'

function TicketListView(): JSX.Element {
    const { tickets, ticketsLoading, conversationsReady } = useValues(sidePanelConversationsLogic)
    const { selectTicket, startNewConversation } = useActions(sidePanelConversationsLogic)

    if (!conversationsReady || ticketsLoading) {
        return (
            <div className="flex items-center justify-center h-40">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonButton type="primary" fullWidth center onClick={startNewConversation}>
                Create new ticket
            </LemonButton>

            {tickets.length === 0 ? (
                <div className="text-center text-muted-alt py-8">
                    <p>No tickets yet.</p>
                    <p className="text-sm">Create a new ticket to get help from our team.</p>
                </div>
            ) : (
                <div className="flex flex-col gap-1 mt-2">
                    {tickets.map((ticket: ConversationTicket) => (
                        <div
                            key={ticket.id}
                            className="flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-surface-light transition-colors bg-surface-primary"
                            onClick={() => selectTicket(ticket.id)}
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <LemonTag
                                        type={
                                            ticket.status === 'resolved'
                                                ? 'success'
                                                : ticket.status === 'new'
                                                  ? 'primary'
                                                  : 'default'
                                        }
                                        size="small"
                                    >
                                        {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                                    </LemonTag>
                                    {(ticket.unread_count ?? 0) > 0 && (
                                        <LemonBadge.Number
                                            count={ticket.unread_count ?? 0}
                                            size="small"
                                            status="primary"
                                        />
                                    )}
                                </div>
                                {ticket.last_message && (
                                    <p className="text-sm text-primary truncate m-0">{ticket.last_message}</p>
                                )}
                                <p className="text-xs text-muted-alt m-0 mt-1">
                                    <TZLabel time={ticket.created_at} />
                                </p>
                            </div>
                            <IconChevronRight className="text-muted-alt" />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function ChatMessage({ message, isCustomer }: { message: ConversationMessage; isCustomer: boolean }): JSX.Element {
    const displayName = message.author_name || (isCustomer ? 'You' : 'Support')

    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'}`}>
            <div className="flex flex-col min-w-0 items-start">
                <div className="text-xs text-muted mb-1 px-1">{displayName}</div>
                <div className="max-w-full">
                    <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                        <p className="text-sm p-0 m-0 whitespace-pre-wrap">{message.content}</p>
                    </div>
                </div>
                <div className="text-xs text-muted-alt mt-1 px-1">
                    <TZLabel time={message.created_at} />
                </div>
            </div>
        </div>
    )
}

function ChatView(): JSX.Element {
    const { messages, messagesLoading, messageSending, currentTicket } = useValues(sidePanelConversationsLogic)
    const { sendMessage, goBack } = useActions(sidePanelConversationsLogic)
    const [messageContent, setMessageContent] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)

    const scrollToBottom = (): void => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

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

    return (
        <div className="flex flex-col h-full bg-surface-primary rounded-lg p-2">
            <div className="flex items-center gap-2 mb-3">
                <LemonButton icon={<IconArrowLeft />} size="small" onClick={goBack} />
                <span className="font-semibold">
                    {currentTicket?.status === 'on_hold' ? 'On hold' : currentTicket?.status}
                </span>
            </div>
            <LemonDivider />
            <div className="flex-1 overflow-y-auto space-y-1.5 min-h-[300px] max-h-[400px] mb-3">
                {messagesLoading ? (
                    <div className="flex items-center justify-center h-full">
                        <Spinner />
                    </div>
                ) : messages.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-muted-alt text-sm">
                        No messages yet.
                    </div>
                ) : (
                    <>
                        {messages.map((message: ConversationMessage) => (
                            <ChatMessage
                                key={message.id}
                                message={message}
                                isCustomer={message.author_type === 'customer'}
                            />
                        ))}
                        <div ref={messagesEndRef} />
                    </>
                )}
            </div>

            <div className="border-t pt-3">
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
        </div>
    )
}

function NewConversationView(): JSX.Element {
    const { messageSending } = useValues(sidePanelConversationsLogic)
    const { sendMessage, goBack } = useActions(sidePanelConversationsLogic)
    const [messageContent, setMessageContent] = useState('')

    const handleSubmit = (): void => {
        if (messageContent.trim()) {
            sendMessage(messageContent)
        }
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <LemonButton icon={<IconArrowLeft />} size="small" onClick={goBack} />
                <span className="font-semibold">New conversation</span>
            </div>

            <p className="text-sm text-muted-alt m-0">
                Describe what you need help with and our team will get back to you.
            </p>

            <LemonTextArea
                placeholder="What can we help you with?"
                value={messageContent}
                onChange={setMessageContent}
                minRows={4}
                disabled={messageSending}
            />

            <LemonButton
                type="primary"
                fullWidth
                center
                onClick={handleSubmit}
                loading={messageSending}
                disabled={!messageContent.trim()}
            >
                Send message
            </LemonButton>
        </div>
    )
}

export function SidePanelConversations(): JSX.Element {
    const { view } = useValues(sidePanelConversationsLogic)

    return (
        <div>
            {view === 'list' && <TicketListView />}
            {view === 'chat' && <ChatView />}
            {view === 'new' && <NewConversationView />}
        </div>
    )
}
