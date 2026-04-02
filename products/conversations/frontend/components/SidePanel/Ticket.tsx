import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { MessageList } from '../Chat/MessageList'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function Ticket(): JSX.Element {
    const { messages, messagesLoading, messageSending, currentTicket } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    return (
        <div className="flex flex-col h-full bg-surface-primary border rounded-lg p-2">
            <div className="flex items-center gap-2">
                <LemonButton icon={<IconArrowLeft />} size="small" onClick={() => setView('list')} />
                {currentTicket?.ticket_number && (
                    <span className="text-xs font-mono text-muted-alt">#{currentTicket.ticket_number}</span>
                )}
                <LemonTag
                    type={
                        currentTicket?.status === 'resolved'
                            ? 'success'
                            : currentTicket?.status === 'new'
                              ? 'primary'
                              : 'default'
                    }
                    size="small"
                >
                    {currentTicket?.status === 'on_hold' ? 'On hold' : currentTicket?.status}
                </LemonTag>
            </div>
            <LemonDivider />
            <MessageList
                messages={messages}
                messagesLoading={messagesLoading}
                emptyMessage="No messages yet."
                minHeight="300px"
                maxHeight="400px"
                className="mb-3"
                isCustomerView
            />
            <div className="border-t pt-3">
                <MessageInput
                    onSendMessage={(content, _richContent, _isPrivate, onSuccess) => sendMessage(content, onSuccess)}
                    messageSending={messageSending}
                />
            </div>
        </div>
    )
}
