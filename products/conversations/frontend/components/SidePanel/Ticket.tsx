import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { MessageList } from '../Chat/MessageList'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function Ticket(): JSX.Element {
    const { messages, messagesLoading, messageSending, currentTicket } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    return (
        <div className="flex flex-col h-full bg-surface-primary border rounded-lg p-2">
            <div className="flex items-center gap-2 mb-3">
                <LemonButton icon={<IconArrowLeft />} size="small" onClick={() => setView('list')} />
                <span className="font-semibold">
                    {currentTicket?.status === 'on_hold' ? 'On hold' : currentTicket?.status}
                </span>
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
                <MessageInput onSendMessage={sendMessage} messageSending={messageSending} />
            </div>
        </div>
    )
}
