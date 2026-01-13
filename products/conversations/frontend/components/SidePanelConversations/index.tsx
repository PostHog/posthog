import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconChevronRight } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonTag, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ConversationTicket } from '../../types'
import { MessageInput, MessageList } from '../Chat'
import { sidePanelConversationsLogic } from './sidePanelConversationsLogic'

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
            <LemonButton
                type="primary"
                fullWidth
                center
                onClick={startNewConversation}
                data-attr="sidebar-create-new-ticket"
            >
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
                            className={`flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-surface-light transition-colors ${
                                (ticket.unread_count ?? 0) > 0 ? 'bg-primary-alt-highlight' : 'bg-white'
                            }`}
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

function ChatView(): JSX.Element {
    const { chatMessages, messagesLoading, messageSending, currentTicket } = useValues(sidePanelConversationsLogic)
    const { sendMessage, goBack } = useActions(sidePanelConversationsLogic)

    return (
        <div className="flex flex-col h-full bg-surface-primary border rounded-lg p-2">
            <div className="flex items-center gap-2 mb-3">
                <LemonButton icon={<IconArrowLeft />} size="small" onClick={goBack} />
                <span className="font-semibold">
                    {currentTicket?.status === 'on_hold' ? 'On hold' : currentTicket?.status}
                </span>
            </div>
            <LemonDivider />
            <MessageList
                messages={chatMessages}
                messagesLoading={messagesLoading}
                emptyMessage="No messages yet."
                minHeight="300px"
                maxHeight="400px"
                className="mb-3"
            />
            <div className="border-t pt-3">
                <MessageInput onSendMessage={sendMessage} messageSending={messageSending} />
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
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    onClick={goBack}
                    data-attr="sidebar-go-back-to-tickets"
                />
                <span className="font-semibold">New ticket</span>
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
                data-attr="sidebar-submit-new-ticket"
            >
                Submit ticket
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
