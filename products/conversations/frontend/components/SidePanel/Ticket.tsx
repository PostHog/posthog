import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { MessageList } from '../Chat/MessageList'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

interface TicketProps {
    /** Hidden in master-detail layouts where the list stays visible alongside the thread */
    showBackButton?: boolean
    /** Lets master-detail layouts show the back button only at widths where the panes stack */
    backButtonClassName?: string
    messagesMinHeight?: string
    messagesMaxHeight?: string
}

export function Ticket({
    showBackButton = true,
    backButtonClassName,
    messagesMinHeight = '300px',
    messagesMaxHeight = '400px',
}: TicketProps): JSX.Element {
    const { messages, messagesLoading, messageSending, currentTicket } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    return (
        <div className="flex flex-col h-full bg-surface-primary border rounded-lg p-2">
            <div className="flex items-center gap-2">
                {showBackButton && (
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="small"
                        className={backButtonClassName}
                        onClick={() => setView('list')}
                    />
                )}
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
                minHeight={messagesMinHeight}
                maxHeight={messagesMaxHeight}
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
